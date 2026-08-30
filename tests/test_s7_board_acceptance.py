from datetime import UTC, datetime

from bilateral_helpers import AllowPolicy, RecordingGateway, create_supplier

from tradefoundry.bilateral.contracts import (
    CandidateWhitelistRequest,
    ConstraintAssessmentRequest,
    FxRateInput,
    InteractionIntake,
    ProductRequirement,
    QualificationCreate,
    QualificationField,
    QuoteComparisonRequest,
    RfqCreate,
    RfqFinalizeRequest,
    SendCommand,
    SupplierCandidateCreate,
    SupplierQuoteIntake,
)
from tradefoundry.bilateral.coordination import ConstraintCoordinationService
from tradefoundry.bilateral.messaging import InteractionService, QualificationService
from tradefoundry.bilateral.outbound import OutboundAuthorizationService, OutboundSendService
from tradefoundry.bilateral.quotes import QuoteComparisonService, SupplierQuoteService
from tradefoundry.bilateral.rfq import RfqService
from tradefoundry.bilateral.suppliers import SupplierDiscoveryService


def test_board7_real_spec_three_quote_formats_buyer_constraint_feedback_and_approved_outbound(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    supplier_records = [
        create_supplier(
            session,
            master_entity_factory,
            master_claim_factory,
            product_concept_factory,
            index=index,
        )
        for index in (1, 2, 3)
    ]
    policy = AllowPolicy()
    for index, (profile, _, source_claim, _) in enumerate(supplier_records, start=1):
        candidate = SupplierDiscoveryService(session).add_candidate(
            route.id,
            SupplierCandidateCreate(
                idempotency_key=f"acceptance-candidate-{index}",
                supplier_profile_id=profile.id,
                discovery_basis=[{"kind": "verified_capability"}],
                source_claim_ids=[source_claim.id],
            ),
        )
        SupplierDiscoveryService(session, policy).whitelist(
            candidate.id, CandidateWhitelistRequest(requested_by="supplier-owner")
        )

    product = supplier_records[0][1]
    rfq = RfqService(session).generate(
        route.id,
        RfqCreate(
            idempotency_key="acceptance-rfq",
            rfq_key="ss316-valve-rfq",
            product_concept_id=product.id,
            destination_country="KE",
            requirement=ProductRequirement(
                specification={"material": "SS316", "pressure_class": "PN16"},
                packaging={"type": "seaworthy_crate"},
                certifications=["ISO 9001"],
                quantity="1",
                quantity_unit="metric_ton",
                requested_delivery_at=datetime(2026, 10, 15, tzinfo=UTC),
                incoterm="CIF",
                payment_terms="Net 60",
            ),
            created_by="commercial-operator",
        ),
    )
    RfqService(session).finalize(
        rfq.id,
        RfqFinalizeRequest(actor="commercial-reviewer", expected_content_hash=rfq.content_hash),
    )
    gateway = RecordingGateway()
    for index, (profile, _, _, _) in enumerate(supplier_records, start=1):
        token = OutboundAuthorizationService(session, policy).authorize_rfq(
            rfq.id, profile.id, requested_by="commercial-operator"
        )
        OutboundSendService(session, gateway).send(
            SendCommand(
                idempotency_key=f"acceptance-rfq-send-{index}",
                token=token.token,
                actor="commercial-operator",
            )
        )

    quote_inputs = [
        ("email", "USD", "10", "kilogram", "CIF", "2", 45, "30% deposit"),
        ("spreadsheet", "EUR", "9000", "metric_ton", "FOB", "1", 60, "LC at sight"),
        ("manual", "CNY", "70", "kilogram", "CIF", "1", 50, "20% deposit"),
    ]
    quotes = []
    for index, ((profile, _, _, _), values) in enumerate(
        zip(supplier_records, quote_inputs, strict=True), start=1
    ):
        intake_format, currency, price, unit, incoterm, moq, lead_days, payment = values
        quotes.append(
            SupplierQuoteService(session).intake(
                route.id,
                SupplierQuoteIntake(
                    idempotency_key=f"acceptance-quote-{index}",
                    supplier_profile_id=profile.id,
                    rfq_version_id=rfq.id,
                    intake_format=intake_format,
                    raw_artifact_ref=f"artifact://acceptance/quote-{index}",
                    raw_hash=str(index) * 64,
                    received_at=datetime(2026, 9, index, tzinfo=UTC),
                    currency=currency,
                    unit_price=price,
                    price_unit=unit,
                    moq_quantity=moq,
                    moq_unit="metric_ton",
                    lead_time_days=lead_days,
                    tax={"included": False},
                    payment_terms=payment,
                    incoterm=incoterm,
                    valid_until=datetime(2026, 10, 1, tzinfo=UTC),
                    specifications={
                        "material": "SS316" if index != 2 else "SS304",
                        "pressure_class": "PN16",
                        "certifications": ["ISO 9001"] if index != 3 else [],
                    },
                ),
            )
        )
    comparison = QuoteComparisonService(session).compare(
        route.id,
        QuoteComparisonRequest(
            idempotency_key="acceptance-comparison",
            quote_ids=[quote.id for quote in quotes],
            target_currency="USD",
            target_unit="metric_ton",
            target_incoterm="CIF",
            fx_rates=[
                FxRateInput(
                    base_currency="EUR",
                    quote_currency="USD",
                    rate="1.10",
                    source_ref="fx:official:eur-usd",
                    as_of=datetime(2026, 9, 3, tzinfo=UTC),
                ),
                FxRateInput(
                    base_currency="CNY",
                    quote_currency="USD",
                    rate="0.14",
                    source_ref="fx:official:cny-usd",
                    as_of=datetime(2026, 9, 3, tzinfo=UTC),
                ),
            ],
            incoterm_adjustments={quotes[1].id: "200"},
        ),
    )

    buyer_reply = InteractionService(session).intake(
        InteractionIntake(
            external_message_id="acceptance-buyer-reply",
            channel="email",
            direction="inbound",
            raw_artifact_ref="artifact://acceptance/buyer-reply",
            raw_hash="b" * 64,
            body_text="We require 30-day delivery and Net 60 payment.",
            occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
            explicit_route_id=route.id,
        )
    )

    def qualified(value):
        return QualificationField(
            value=value, source_interaction_id=buyer_reply.id, confidence=0.98
        )

    qualification = QualificationService(session).snapshot(
        route.id,
        QualificationCreate(
            idempotency_key="acceptance-qualification",
            as_of=datetime(2026, 9, 4, tzinfo=UTC),
            quantity=qualified({"amount": 1, "unit": "metric_ton"}),
            specification=qualified(
                {
                    "certifications": ["ISO 9001"],
                    "specifications": {"material": "SS316", "pressure_class": "PN16"},
                }
            ),
            timing=qualified({"required_lead_time_days": 30}),
            procurement_process=qualified({"payment_terms": "Net 60"}),
        ),
    )
    assessment = ConstraintCoordinationService(session).assess(
        route.id,
        ConstraintAssessmentRequest(
            idempotency_key="acceptance-constraints",
            qualification_snapshot_id=qualification.id,
            quote_ids=[quote.id for quote in quotes],
        ),
    )

    assert len(gateway.payloads) == 3
    assert sum(call.action_kind == "supplier_rfq" for call in policy.authorization_calls) == 3
    assert comparison.incomparable_quote_ids_json == []
    assert {row["normalized"]["unit_price"] for row in comparison.rows_json} == {
        "10000.0000",
        "10100.0000",
        "9800.0000",
    }
    assert {item["type"] for item in assessment.conflicts_json} >= {
        "moq",
        "lead_time",
        "certification",
        "specification",
        "payment_terms",
    }
    assert {item["action"] for item in assessment.candidate_solutions_json} >= {
        "switch_supplier",
        "aggregate_buyers",
        "trade_finance",
        "adjust_specification",
    }
