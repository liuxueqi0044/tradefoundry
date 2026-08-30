from datetime import UTC, datetime
from decimal import Decimal

from bilateral_helpers import StaticCostScenarios, create_supplier

from tradefoundry.bilateral.contracts import (
    BuyerQuoteBuildRequest,
    ConstraintAssessmentRequest,
    InteractionIntake,
    MeetingActionItem,
    MeetingImport,
    NegotiationTermCreate,
    QualificationCreate,
    QualificationField,
    SupplierQuoteIntake,
)
from tradefoundry.bilateral.coordination import (
    BuyerQuoteService,
    ConstraintCoordinationService,
    MeetingSyncService,
    NegotiationTermService,
)
from tradefoundry.bilateral.messaging import InteractionService, QualificationService
from tradefoundry.bilateral.quotes import SupplierQuoteService


def _qualification_source(session, route_id):
    return InteractionService(session).intake(
        InteractionIntake(
            external_message_id="constraint-source-message",
            channel="email",
            direction="inbound",
            raw_artifact_ref="artifact://interaction/constraint",
            raw_hash="c" * 64,
            body_text="100 SS316 valves, ISO 9001, 30 days, Net 60.",
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
            explicit_route_id=route_id,
        )
    )


def test_constraint_coordinator_detects_five_conflict_types_and_only_proposes_candidates(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    supplier, _, _, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    source = _qualification_source(session, route.id)

    def field(value):
        return QualificationField(value=value, source_interaction_id=source.id, confidence=0.95)

    qualification = QualificationService(session).snapshot(
        route.id,
        QualificationCreate(
            idempotency_key="constraint-qualification",
            as_of=datetime(2026, 9, 2, tzinfo=UTC),
            quantity=field({"amount": 100, "unit": "piece"}),
            specification=field(
                {
                    "certifications": ["ISO 9001"],
                    "specifications": {"material": "SS316"},
                }
            ),
            timing=field({"required_lead_time_days": 30}),
            procurement_process=field({"payment_terms": "Net 60"}),
        ),
    )
    quote = SupplierQuoteService(session).intake(
        route.id,
        SupplierQuoteIntake(
            idempotency_key="constraint-supplier-quote",
            supplier_profile_id=supplier.id,
            intake_format="spreadsheet",
            raw_artifact_ref="artifact://quote/constraint",
            raw_hash="d" * 64,
            received_at=datetime(2026, 9, 2, tzinfo=UTC),
            currency="USD",
            unit_price="9",
            price_unit="piece",
            moq_quantity="500",
            moq_unit="piece",
            lead_time_days=60,
            tax={"included": False},
            payment_terms="30% deposit",
            incoterm="FOB",
            valid_until=datetime(2026, 10, 1, tzinfo=UTC),
            specifications={"material": "SS304", "certifications": []},
        ),
    )
    assessment = ConstraintCoordinationService(session).assess(
        route.id,
        ConstraintAssessmentRequest(
            idempotency_key="constraint-assessment",
            qualification_snapshot_id=qualification.id,
            quote_ids=[quote.id],
        ),
    )

    assert {item["type"] for item in assessment.conflicts_json} == {
        "moq",
        "lead_time",
        "certification",
        "specification",
        "payment_terms",
    }
    assert assessment.route_reassessment_required is True
    assert all(
        item["status"] == "candidate_only" and item["requires_human_decision"]
        for item in assessment.candidate_solutions_json
    )
    assert {item["action"] for item in assessment.candidate_solutions_json} >= {
        "switch_supplier",
        "aggregate_buyers",
        "adjust_specification",
        "trade_finance",
    }


def test_buyer_quote_uses_versioned_cost_port_and_stays_unapproved_draft(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    quote = BuyerQuoteService(session, StaticCostScenarios()).build(
        route.id,
        BuyerQuoteBuildRequest(
            idempotency_key="buyer-quote-1",
            quote_key="buyer-offer",
            cost_scenario_ref="cost:scenario:1",
            margin_rate=Decimal("0.20"),
            valid_until=datetime(2026, 9, 30, tzinfo=UTC),
            created_by="commercial-owner",
        ),
    )

    assert quote.cost_amount == Decimal("800.0000")
    assert quote.selling_amount == Decimal("1000.0000")
    assert quote.cost_status == "estimated"
    assert quote.status == "draft"
    assert quote.approval_status == "pending"
    assert quote.cost_scenario_hash == "a" * 64
    assert any("estimated" in item for item in quote.assumptions_json)


def test_negotiation_versions_are_immutable_diffed_and_floor_breach_requires_approval(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    service = NegotiationTermService(session)
    floors = {
        "unit_price": {"operator": "gte", "value": 10},
        "lead_time_days": {"operator": "lte", "value": 60},
        "payment_days": {"operator": "lte", "value": 45},
        "warranty_months": {"operator": "lte", "value": 24},
    }
    first = service.append(
        route.id,
        NegotiationTermCreate(
            idempotency_key="terms-v1",
            term_key="buyer-negotiation",
            counterparty_ref="buyer:1",
            terms={
                "unit_price": 11,
                "lead_time_days": 45,
                "payment_days": 30,
                "warranty_months": 12,
            },
            internal_floors=floors,
            created_by="owner",
        ),
    )
    second = service.append(
        route.id,
        NegotiationTermCreate(
            idempotency_key="terms-v2",
            term_key="buyer-negotiation",
            counterparty_ref="buyer:1",
            terms={
                "unit_price": 9,
                "lead_time_days": 45,
                "payment_days": 60,
                "warranty_months": 12,
            },
            internal_floors=floors,
            created_by="owner",
        ),
    )

    assert first.version_no == 1
    assert first.terms_json["unit_price"] == 11
    assert first.approval_required is False
    assert second.version_no == 2
    assert second.diff_json == {
        "payment_days": {"from": 30, "to": 60},
        "unit_price": {"from": 11, "to": 9},
    }
    assert second.approval_required is True
    assert {item["field"] for item in second.floor_violations_json} == {
        "unit_price",
        "payment_days",
    }


def test_meeting_import_creates_route_linked_action_proposals_idempotently(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    request = MeetingImport(
        external_ref="calendar:event:123",
        raw_artifact_ref="artifact://meeting/123",
        raw_hash="e" * 64,
        summary="Buyer requested a revised specification and sample plan.",
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        imported_by="calendar-operator",
        action_items=[
            MeetingActionItem(
                task_key="revise-spec",
                owner="technical-owner",
                description="Prepare revised specification matrix.",
                due_at=datetime(2026, 9, 6, tzinfo=UTC),
            ),
            MeetingActionItem(
                task_key="sample-plan",
                owner="supplier-owner",
                description="Confirm sample production plan.",
                due_at=datetime(2026, 9, 7, tzinfo=UTC),
            ),
        ],
    )
    first = MeetingSyncService(session).import_meeting(route.id, request)
    replay = MeetingSyncService(session).import_meeting(route.id, request)

    assert first.duplicate is False
    assert replay.duplicate is True
    assert replay.meeting_import_id == first.meeting_import_id
    assert replay.interaction_id == first.interaction_id
    assert set(replay.task_ids) == set(first.task_ids)
    assert len(first.task_ids) == 2
