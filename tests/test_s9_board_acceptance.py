from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from control_helpers import approved_action
from sqlalchemy import select

from tradefoundry.controltower.contracts import Decision, ExecutionTokenIssue, PolicyRule
from tradefoundry.controltower.governance import ExecutionTokenService
from tradefoundry.controltower.models import LandedCostScenarioRow
from tradefoundry.deals.contracts import ObservationCreate, RouteStage, StageTransitionRequest
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.deals.observations import ObservationService
from tradefoundry.deals.state_machine import RouteStageService
from tradefoundry.evidence.models import ClaimEvidenceRow
from tradefoundry.execution.adapters import DealsCollectionPublisher
from tradefoundry.execution.contracts_learning import (
    DashboardSnapshotRequest,
    EvaluationRequest,
    LearningDatasetBuildRequest,
    LearningObservation,
    OutcomeBuildRequest,
    PredictionActualRequest,
    ReviewProposalRequest,
)
from tradefoundry.execution.contracts_orders import (
    CommitmentEvidence,
    ErpResource,
    MilestoneRecord,
    OrderCommand,
    ShipmentDocument,
)
from tradefoundry.execution.contracts_settlement import (
    ActualCostCreate,
    BankReconciliation,
    InvoiceRefCreate,
    PaymentAllocationCreate,
    PaymentRefCreate,
    PnlSnapshotCreate,
    QualityCaseCreate,
    QualityClose,
)
from tradefoundry.execution.dashboard import DashboardService
from tradefoundry.execution.documents import ShipmentDocumentService
from tradefoundry.execution.erp import ErpMappingService, RecordingErpGateway
from tradefoundry.execution.evaluation import EvaluationService
from tradefoundry.execution.fulfillment import FulfillmentService
from tradefoundry.execution.learning import (
    LearningDatasetService,
    OutcomeBuilder,
    PredictionActualService,
)
from tradefoundry.execution.orders import OrderService
from tradefoundry.execution.pnl import PnlService
from tradefoundry.execution.ports import ControlTowerTokenGuard
from tradefoundry.execution.quality import QualityCaseService
from tradefoundry.execution.reviews import ReviewProposalService
from tradefoundry.execution.settlement import (
    InvoiceSettlementService,
    PaymentSettlementService,
)
from tradefoundry.tradealpha.models import (
    FeatureSnapshotRow,
    ProbabilityEstimateRow,
    ScoreSnapshotRow,
    ScoringPolicyRow,
)

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)


def _evidence(session, claim):
    return CommitmentEvidence(
        claim_id=claim.id,
        evidence_fragment_ids=[
            session.scalar(
                select(ClaimEvidenceRow.fragment_id).where(ClaimEvidenceRow.claim_id == claim.id)
            )
        ],
    )


def _invoice(order_id: str, key: str, kind: str, amount: str):
    return InvoiceRefCreate(
        idempotency_key=key,
        order_id=order_id,
        invoice_kind=kind,
        invoice_ref=f"ERP-{key}",
        amount=Decimal(amount),
        currency="USD",
        invoice_date=date(2026, 8, 20),
        evidence_refs=[f"erp-invoice:{key}"],
    )


def test_board9_closes_committed_trade_into_cash_pnl_outcome_and_safe_learning(
    session,
    deal_route_factory,
    master_claim_factory,
    master_entity_factory,
    product_concept_factory,
):
    _, route_view = deal_route_factory()
    route = session.get(DealRouteRow, route_view.id)
    customer = master_entity_factory(name="Board Nine Buyer")
    product = product_concept_factory(label="Board Nine Valve")
    commitment_claim = master_claim_factory(
        value="Buyer purchase order PO-9001", field_path="trade.commitment", verified=True
    )
    evidence = _evidence(session, commitment_claim)

    # Board 7 hands over a quoted route plus a formal commitment observation.
    route.stage = "quoted"
    session.commit()
    ObservationService(session).record(
        route.id,
        ObservationCreate(
            idempotency_key="board9-purchase-order-observation",
            observation_type="purchase_order",
            raw_text="Verified buyer purchase order PO-9001.",
            evidence_claim_id=commitment_claim.id,
            occurred_at=NOW - timedelta(days=10),
        ),
    )
    committed = RouteStageService(session).transition(
        route.id,
        StageTransitionRequest(
            idempotency_key="board9-route-committed",
            expected_version=route.version,
            to_stage=RouteStage.COMMITTED,
            actor="deal-owner",
            reason="Verified buyer purchase order accepted.",
        ),
    )
    assert committed.outcome == "accepted"
    session.refresh(route)

    # S9.1: sandbox ERP adapter establishes durable mappings and attempt history.
    for resource_type, internal_id, external_id in (
        ("Customer", customer.id, "ERP-CUSTOMER-9001"),
        ("Item", product.id, "ERP-ITEM-9001"),
    ):
        gateway = RecordingErpGateway()
        gateway.result = gateway.result or None
        mapping = ErpMappingService(session, gateway)
        queued = mapping.queue(
            ErpResource(
                resource_type=resource_type,
                internal_id=internal_id,
                payload={"fixture_external_id": external_id},
                idempotency_key=f"board9-map-{resource_type.lower()}",
            )
        )
        # The fixture gateway returns a deterministic external ID; keep that ID
        # as the contract fact used by the order payload.
        assert mapping.dispatch(queued.id).status == "succeeded"

    preliminary = OrderCommand(
        order_key="board9-sales-order",
        idempotency_key="board9-sales-order-command",
        route_id=route.id,
        order_kind="sales",
        customer_entity_id=customer.id,
        item_ref=product.id,
        quantity=Decimal("10"),
        quantity_unit="each",
        unit_price=Decimal("100"),
        currency="USD",
        terms={"incoterm": "FOB"},
        commitment=evidence,
        policy_decision_id="pending",
        approval_request_id="pending",
        execution_token="pending",
        requested_by="operator-1",
    )
    rules = [
        PolicyRule(
            rule_key="board9-order-requires-approval",
            priority=100,
            actions=["create_order"],
            effect=Decision.REQUIRE_APPROVAL,
            conditions=[],
            reasons=["All ERP orders require independent approval."],
            obligations={
                "approval_chain": [{"role": "compliance", "approvals": 1}],
                "separation_of_duties": True,
            },
        )
    ]
    policy, approval, params = approved_action(
        session,
        action="create_order",
        resource_type="order",
        resource_id=preliminary.order_key,
        params=preliminary.token_params(),
        subject_refs=[customer.id, route.id],
        suffix="board9-order",
        rules=rules,
    )
    token = ExecutionTokenService(session).issue(
        ExecutionTokenIssue(
            approval_request_id=approval.id,
            params=params,
            issued_by="control-tower",
        )
    )
    command = preliminary.model_copy(
        update={
            "policy_decision_id": policy.id,
            "approval_request_id": approval.id,
            "execution_token": token.token,
        }
    )
    orders = OrderService(session, ControlTowerTokenGuard(ExecutionTokenService(session)))
    order = orders.issue(command)
    order = orders.dispatch(order.id, execution_token=token.token, gateway=RecordingErpGateway())
    assert order.status == "succeeded"

    # S9.4/S9.5: partial shipment stays explicit and its full document set is evidence-backed.
    milestone = FulfillmentService(session).record(
        MilestoneRecord(
            shipment_id="shipment-9001",
            milestone_key="delivery",
            version_no=1,
            planned_at=NOW - timedelta(days=5),
            actual_at=NOW - timedelta(days=3),
            planned_quantity=Decimal("10"),
            actual_quantity=Decimal("4"),
            quantity_unit="each",
            evidence=evidence,
        )
    )
    assert milestone.delivery_status == "partial" and milestone.late_days == 2
    documents = ShipmentDocumentService(session)
    for index, document_type in enumerate(
        ("invoice", "packing_list", "bill_of_lading", "customs", "certificate")
    ):
        documents.add(
            ShipmentDocument(
                shipment_id="shipment-9001",
                document_type=document_type,
                version_no=1,
                storage_ref=f"s3://board9/{document_type}.pdf",
                content_hash=str(index + 1) * 64,
                evidence=evidence,
                related_document_versions={
                    key: 1
                    for key in (
                        "invoice",
                        "packing_list",
                        "bill_of_lading",
                        "customs",
                        "certificate",
                    )
                },
            )
        )
    assert documents.validate("shipment-9001", now=NOW) == []

    # S9.6/S9.7: deposit alone is insufficient; the final collection signal
    # exists only after both invoice allocation and bank reconciliation.
    invoice_service = InvoiceSettlementService(session)
    sales_invoice = invoice_service.record_invoice(
        _invoice(order.id, "sales-9001", "sales", "1000")
    )
    purchase_invoice = invoice_service.record_invoice(
        _invoice(order.id, "purchase-9001", "purchase", "400")
    )
    payment_service = PaymentSettlementService(
        session, publisher=DealsCollectionPublisher(session)
    )
    deposit = payment_service.record_payment(
        PaymentRefCreate(
            idempotency_key="board9-deposit",
            order_id=order.id,
            payment_ref="BANK-DEPOSIT-9001",
            amount=Decimal("300"),
            currency="USD",
            paid_at=NOW - timedelta(days=8),
            bank_ref="STATEMENT-DEP-9001",
            fee_amount=Decimal("5"),
            evidence_refs=["bank:deposit-9001"],
        )
    )
    payment_service.allocate(
        PaymentAllocationCreate(
            idempotency_key="board9-deposit-allocation",
            payment_id=deposit.id,
            invoice_id=sales_invoice.id,
            amount=Decimal("300"),
            currency="USD",
            evidence_refs=["erp:allocation-deposit"],
        )
    )
    payment_service.reconcile_bank(
        BankReconciliation(
            payment_id=deposit.id,
            reconciliation_ref="ERP-RECON-DEPOSIT",
            evidence_refs=["bank-reconciliation:deposit"],
            reconciled_at=NOW - timedelta(days=7),
        )
    )
    assert payment_service.emit_collection_signal(order.id) is None
    tail = payment_service.record_payment(
        PaymentRefCreate(
            idempotency_key="board9-tail",
            order_id=order.id,
            payment_ref="BANK-TAIL-9001",
            amount=Decimal("700"),
            currency="USD",
            paid_at=NOW - timedelta(hours=2),
            bank_ref="STATEMENT-TAIL-9001",
            fee_amount=Decimal("5"),
            fx_difference=Decimal("5"),
            evidence_refs=["bank:tail-9001"],
        )
    )
    payment_service.allocate(
        PaymentAllocationCreate(
            idempotency_key="board9-tail-allocation",
            payment_id=tail.id,
            invoice_id=sales_invoice.id,
            amount=Decimal("700"),
            currency="USD",
            evidence_refs=["erp:allocation-tail"],
        )
    )
    assert payment_service.emit_collection_signal(order.id) is None
    payment_service.reconcile_bank(
        BankReconciliation(
            payment_id=tail.id,
            reconciliation_ref="ERP-RECON-TAIL",
            evidence_refs=["bank-reconciliation:tail"],
            reconciled_at=NOW - timedelta(hours=1),
        )
    )
    collected = payment_service.emit_collection_signal(order.id)
    session.refresh(route)
    assert collected.status == "published" and route.stage == "collected"

    # S9.8/S9.9: realized quality loss, fees, FX and logistics all reach PnL.
    quality = QualityCaseService(session)
    quality_case = quality.open_case(
        QualityCaseCreate(
            idempotency_key="board9-quality",
            order_id=order.id,
            batch_ref="BATCH-9001",
            supplier_ref="SUPPLIER-9001",
            buyer_ref=customer.id,
            case_type="defect",
            description="Four units required rework.",
            reported_by="warehouse-inspector",
            evidence_refs=["inspection:9001"],
            reserve_amount=Decimal("40"),
            currency="USD",
        )
    )
    quality.close_case(
        QualityClose(
            idempotency_key="board9-quality-close",
            case_id=quality_case.id,
            conclusion="Supplier accepted a USD 30 quality debit.",
            independent_reviewer="quality-reviewer",
            evidence_refs=["claim-settlement:9001"],
            final_loss=Decimal("30"),
            currency="USD",
        )
    )
    pnl_service = PnlService(session)
    pnl_service.record_actual_cost(
        ActualCostCreate(
            idempotency_key="board9-logistics-cost",
            order_id=order.id,
            category="logistics",
            amount=Decimal("100"),
            currency="USD",
            source_reference="FREIGHT-9001",
            evidence_refs=["freight-invoice:9001"],
            erp_gl_ref="ERP-GL-FREIGHT-9001",
        )
    )
    pnl = pnl_service.snapshot(
        PnlSnapshotCreate(
            idempotency_key="board9-pnl",
            order_id=order.id,
            currency="USD",
            erp_ledger_total=Decimal("455"),
            erp_ledger_ref="ERP-GL-CLOSE-9001",
            evidence_refs=["erp-ledger-close:9001"],
            as_of=NOW,
        )
    )
    assert pnl.contribution == Decimal("455.0000")
    assert pnl.reconciliation_status == "reconciled"

    # S9.10/S9.11: outcome and prediction error use pinned immutable facts.
    outcome = OutcomeBuilder(session).build(
        OutcomeBuildRequest(
            route_id=route.id,
            idempotency_key="board9-success-outcome",
            outcome_cutoff_at=NOW,
            status="success",
            order_id=order.id,
            pnl_snapshot_id=pnl.id,
            collection_signal_id=collected.id,
            milestone_ids=[milestone.id],
            shipment_ids=["shipment-9001"],
            quality_case_ids=[quality_case.id],
            currency="USD",
        )
    )
    assert outcome.actual_price == Decimal("1000.0000")
    assert outcome.pnl == Decimal("455.0000")
    no_reply = OutcomeBuilder(session).build(
        OutcomeBuildRequest(
            route_id=route.id,
            idempotency_key="board9-no-reply-outcome",
            outcome_cutoff_at=NOW,
            status="no_reply",
            failed_stage="qualification",
            reasons=["No response before the configured stop deadline."],
        )
    )
    prediction_at = NOW - timedelta(days=11)
    prediction_feature = FeatureSnapshotRow(
        id="board9-prediction-feature",
        route_id=route.id,
        idempotency_key="board9-prediction-feature",
        request_hash="0" * 64,
        as_of=prediction_at,
        registry_hash="1" * 64,
        features_json={"route_readiness": 0.7},
        sources_json={"route": route.id},
        context_json={},
        completeness=1,
        source_max_available_at=prediction_at,
        created_at=prediction_at,
    )
    scoring_policy = ScoringPolicyRow(
        id="board9-scoring-policy",
        policy_key="board9-baseline",
        version_no=1,
        idempotency_key="board9-scoring-policy",
        request_hash="2" * 64,
        name="Board 9 baseline",
        status="active",
        weights_json={"route_readiness": 1.0},
        hard_rules_json=[],
        missing_strategy="zero",
        created_by="risk-engine",
        created_at=prediction_at,
    )
    score = ScoreSnapshotRow(
        id="board9-score",
        route_id=route.id,
        feature_snapshot_id=prediction_feature.id,
        policy_id=scoring_policy.id,
        idempotency_key="board9-score",
        request_hash="a" * 64,
        as_of=prediction_at,
        scoring_mode="rule_baseline",
        factors_json=[],
        total_score=0.7,
        hard_decision="allow",
        hard_reasons_json=[],
        assumptions_json=[],
        gaps_json=[],
        sensitivities_json=[],
        created_at=prediction_at,
    )
    probability = ProbabilityEstimateRow(
        id="board9-probability",
        route_id=route.id,
        idempotency_key="board9-probability",
        request_hash="b" * 64,
        as_of=prediction_at,
        estimator_version="v1",
        context_json={},
        stages_json=[],
        overall_mean=0.75,
        overall_low=0.5,
        overall_high=0.9,
        sample_size=100,
        created_at=prediction_at,
    )
    cost = LandedCostScenarioRow(
        id="board9-cost",
        scenario_key="board9-cost",
        version_no=1,
        idempotency_key="board9-cost",
        request_hash="c" * 64,
        route_id=route.id,
        currency="USD",
        quantity=10,
        quantity_unit="each",
        incoterm="FOB",
        destination_country="KE",
        goods_amount=Decimal("400"),
        goods_currency="USD",
        goods_amount_normalized=Decimal("400"),
        total_low=Decimal("450"),
        total_base=Decimal("500"),
        total_high=Decimal("550"),
        assumptions_json=[],
        missing_inputs_json=[],
        calculator_version="v1",
        input_hash="d" * 64,
        status="active",
        created_by="risk-engine",
        created_at=prediction_at,
    )
    session.add_all([prediction_feature, scoring_policy, score, probability, cost])
    session.commit()
    comparison = PredictionActualService(session).compare(
        PredictionActualRequest(
            outcome_id=outcome.id,
            idempotency_key="board9-prediction-actual",
            prediction_cutoff_at=prediction_at,
            score_snapshot_id=score.id,
            probability_estimate_id=probability.id,
            board8_cost_snapshot_id=cost.id,
            pnl_snapshot_id=pnl.id,
        )
    )
    assert comparison.actual_cost == Decimal("545.0000")
    assert comparison.cost_error == Decimal("45.0000")

    # S9.12-S9.15: failure-inclusive, leakage-safe dataset; challenger only
    # becomes review-eligible; dashboard uses fixed realized KPI definitions.
    for feature_id in ("board9-feature-success", "board9-feature-no-reply"):
        session.add(
            FeatureSnapshotRow(
                id=feature_id,
                route_id=route.id,
                idempotency_key=feature_id,
                request_hash="e" * 64,
                as_of=NOW - timedelta(days=1),
                registry_hash="f" * 64,
                features_json={"score": 0.7},
                sources_json={"route": route.id},
                context_json={},
                completeness=1,
                source_max_available_at=NOW - timedelta(days=1),
                created_at=NOW - timedelta(days=1),
            )
        )
    session.commit()
    dataset = LearningDatasetService(session).build(
        LearningDatasetBuildRequest(
            dataset_key="board9-routes",
            idempotency_key="board9-dataset",
            observations=[
                LearningObservation(
                    observation_id="a-success",
                    outcome_id=outcome.id,
                    route_id=route.id,
                    observation_cutoff=NOW - timedelta(days=1),
                    feature_snapshot_id="board9-feature-success",
                    label="success",
                ),
                LearningObservation(
                    observation_id="b-no-reply",
                    outcome_id=no_reply.id,
                    route_id=route.id,
                    observation_cutoff=NOW - timedelta(days=1),
                    feature_snapshot_id="board9-feature-no-reply",
                    label="no_reply",
                    human_intervention=True,
                ),
            ],
        )
    )
    report = EvaluationService(session).evaluate(
        EvaluationRequest(
            dataset_id=dataset.id,
            idempotency_key="board9-evaluation",
            evaluated_at=NOW,
            training_cutoff=NOW - timedelta(days=30),
            validation_start=NOW - timedelta(days=2),
            validation_end=NOW,
            baseline_predictions=[0.8, 0.8],
            challenger_predictions=[0.9, 0.1],
            labels=[True, False],
            slices=[
                {
                    "name": "all_routes",
                    "predictions": [0.9, 0.1],
                    "labels": [True, False],
                }
            ],
            economic={"baseline": 455, "challenger": 500},
            safety={"checks": {"loss_limit": True, "privacy": True}},
        )
    )
    assert report.eligible
    proposal = ReviewProposalService(session).propose(
        ReviewProposalRequest(
            idempotency_key="board9-review-proposal",
            proposal_type="model",
            subject_ref="challenger:v1",
            proposal={"action": "review_for_promotion"},
            evidence_refs=[report.id, dataset.id],
            created_by="evaluation-worker",
        )
    )
    assert proposal.status == "review_pending"
    dashboard = DashboardService(session).snapshot(
        DashboardSnapshotRequest(
            snapshot_key="board9-weekly",
            idempotency_key="board9-dashboard",
            as_of=NOW,
            reporting_currency="USD",
            invoice_ids=[sales_invoice.id, purchase_invoice.id],
            pnl_snapshot_ids=[pnl.id],
            outcome_ids=[outcome.id],
        )
    )
    assert dashboard.sales_json["gross_sales"] == "1000.0000"
    assert dashboard.contribution_json["contribution_pnl"] == "455.0000"
