from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradefoundry.controltower.models import LandedCostScenarioRow
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.execution.contracts_learning import (
    DashboardSnapshotRequest,
    EvaluationRequest,
    LearningDatasetBuildRequest,
    LearningObservation,
    OutcomeBuildRequest,
    PredictionActualRequest,
    ReviewProposalRequest,
)
from tradefoundry.execution.dashboard import DashboardService
from tradefoundry.execution.evaluation import EvaluationService
from tradefoundry.execution.learning import (
    LearningDatasetService,
    OutcomeBuilder,
    PredictionActualService,
)
from tradefoundry.execution.models_learning import (  # noqa: F401
    DashboardSnapshotRow,
    EvaluationReportRow,
    LearningDatasetItemRow,
    LearningDatasetRow,
    OutcomeRow,
    PredictionActualRow,
    ReviewProposalRow,
)
from tradefoundry.execution.models_orders import OrderCommandRow
from tradefoundry.execution.models_settlement import (
    CollectionSignalRow,
    ContributionPnlSnapshotRow,
    InvoiceRefRow,
)
from tradefoundry.execution.reviews import ReviewProposalService
from tradefoundry.tradealpha.models import (
    FeatureSnapshotRow,
    ProbabilityEstimateRow,
    ScoreSnapshotRow,
)

AT = datetime(2026, 8, 31, 12, tzinfo=UTC)


def outcome(session, status="success", key="outcome-1"):
    if session.get(DealRouteRow, "route-1") is None:
        session.add(
            DealRouteRow(
                id="route-1",
                cell_id="cell-1",
                route_key="fixture",
                request_hash="a" * 64,
                route_type="buyer_supplier",
                budget_limit=1000,
                currency="USD",
            )
        )
        session.flush()
    refs = {}
    if status == "success":
        order = OrderCommandRow(
            id="order-1",
            order_key="order-key",
            idempotency_key="order-key-idem",
            request_hash="b" * 64,
            order_kind="sales",
            route_id="route-1",
            item_ref="item",
            quantity=10,
            quantity_unit="each",
            unit_price=10,
            currency="USD",
            terms_json={},
            commitment_claim_id="claim",
            commitment_evidence_ids_json=[],
            policy_decision_id="p",
            approval_request_id="a",
            token_id="t",
            params_hash="c" * 64,
            requested_by="test",
            status="succeeded",
            created_at=AT - timedelta(days=12),
        )
        session.add(order)
        session.add(
            ContributionPnlSnapshotRow(
                id="pnl-1",
                idempotency_key="pnl-key",
                request_hash="d" * 64,
                order_id=order.id,
                as_of=AT - timedelta(days=2),
                currency="USD",
                revenue=100,
                procurement=50,
                logistics=0,
                financing=0,
                fx=0,
                commission=0,
                warranty=0,
                claims_refunds=0,
                contribution=50,
                erp_ledger_total=50,
                erp_ledger_ref="ERP-GL-OUTCOME-1",
                reconciliation_difference=0,
                reconciliation_status="reconciled",
                source_refs_json={},
                evidence_refs_json=[],
                created_at=AT - timedelta(days=2),
            )
        )
        session.add(
            CollectionSignalRow(
                id="collection-1",
                signal_key="collection:order-1",
                order_id=order.id,
                total_invoiced=100,
                total_allocated=100,
                currency="USD",
                payment_ids_json=[],
                invoice_ids_json=[],
                evidence_refs_json=[],
                status="published",
                published_at=AT,
            )
        )
        session.flush()
        refs = {
            "order_id": "order-1",
            "pnl_snapshot_id": "pnl-1",
            "collection_signal_id": "collection-1",
        }
    return OutcomeBuilder(session).build(
        OutcomeBuildRequest(
            route_id="route-1",
            idempotency_key=key,
            outcome_cutoff_at=AT,
            status=status,
            **refs,
            interaction={"replies": 1},
            qualification={"qualified": status == "success"},
            quote={"currency": "USD"},
            commit={"committed": status == "success"},
            delivery={"delivered": status == "success"},
            collection={"actual_cost": "50"},
            actual_price=Decimal("100") if status == "success" else None,
            pnl=Decimal("50") if status == "success" else None,
            peak_capital=Decimal("70"),
            days=Decimal("12"),
            failed_stage=None if status == "success" else "qualification",
            reasons=[] if status == "success" else ["buyer stopped replying"],
        )
    )


def test_outcome_builder_retains_success_and_no_reply_with_structured_facts(session):
    success = outcome(session)
    stopped = outcome(session, "no_reply", "outcome-2")
    assert success.success and not success.no_reply
    assert not stopped.success and stopped.no_reply
    assert stopped.failed_stage == "qualification"
    assert stopped.reasons_json == ["buyer stopped replying"]
    assert success.interaction_json["replies"] == 1
    assert success.pnl == Decimal("50.0000")


def test_prediction_actual_rejects_post_outcome_prediction_and_calculates_errors(session):
    result = outcome(session)
    prediction_at = AT - timedelta(days=1)
    session.add(
        ScoreSnapshotRow(
            id="score-1",
            route_id="route-1",
            feature_snapshot_id="feature",
            policy_id="policy",
            model_version_id=None,
            idempotency_key="score-key",
            request_hash="1" * 64,
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
    )
    session.add(
        ProbabilityEstimateRow(
            id="prob-1",
            route_id="route-1",
            feature_snapshot_id=None,
            idempotency_key="prob-key",
            request_hash="2" * 64,
            as_of=prediction_at,
            estimator_version="v1",
            context_json={},
            stages_json=[],
            overall_mean=0.8,
            overall_low=0.1,
            overall_high=0.9,
            sample_size=1,
            created_at=prediction_at,
        )
    )
    session.add(
        LandedCostScenarioRow(
            id="cost-1",
            scenario_key="cost",
            version_no=1,
            idempotency_key="cost-key",
            request_hash="3" * 64,
            route_id="route-1",
            supplier_quote_id=None,
            currency="USD",
            quantity=10,
            quantity_unit="each",
            gross_weight_kg=None,
            incoterm="FOB",
            destination_country="US",
            goods_amount=60,
            goods_currency="USD",
            goods_amount_normalized=60,
            total_low=50,
            total_base=60,
            total_high=70,
            assumptions_json=[],
            missing_inputs_json=[],
            calculator_version="v1",
            input_hash="4" * 64,
            status="active",
            created_by="test",
            created_at=prediction_at,
        )
    )
    session.commit()
    compared = PredictionActualService(session).compare(
        PredictionActualRequest(
            outcome_id=result.id,
            idempotency_key="comparison-1",
            prediction_cutoff_at=prediction_at,
            score_snapshot_id="score-1",
            probability_estimate_id="prob-1",
            board8_cost_snapshot_id="cost-1",
            pnl_snapshot_id="pnl-1",
            predicted_cycle_days=Decimal("10"),
        )
    )
    assert compared.cost_error == Decimal("-10.0000")
    assert compared.cycle_error == Decimal("2.0000")
    with pytest.raises(ValueError, match="before outcome"):
        PredictionActualService(session).compare(
            PredictionActualRequest(
                outcome_id=result.id,
                idempotency_key="comparison-late",
                prediction_cutoff_at=AT + timedelta(seconds=1),
                score_snapshot_id="score-1",
                probability_estimate_id="prob-1",
                board8_cost_snapshot_id="cost-1",
                pnl_snapshot_id="pnl-1",
            )
        )


def test_dataset_rejects_feature_leakage_and_keeps_failure_labels(session):
    success = outcome(session, "success", "dataset-success")
    failure = outcome(session, "failure", "dataset-failure")
    no_reply = outcome(session, "no_reply", "dataset-no-reply")
    for index in range(3):
        session.add(
            FeatureSnapshotRow(
                id=f"feature-{index}",
                route_id="route-1",
                idempotency_key=f"feature-key-{index}",
                request_hash="e" * 64,
                as_of=AT - timedelta(days=1),
                registry_hash="f" * 64,
                features_json={},
                sources_json={},
                context_json={},
                completeness=1,
                source_max_available_at=AT - timedelta(days=1),
                created_at=AT - timedelta(days=1),
            )
        )
    session.commit()
    with pytest.raises(ValueError, match="feature snapshot"):
        LearningDatasetService(session).build(
            LearningDatasetBuildRequest(
                dataset_key="routes",
                idempotency_key="dataset-leak",
                observations=[
                    LearningObservation(
                        observation_id="leak",
                        feature_snapshot_id="feature-0",
                        outcome_id=success.id,
                        route_id="route-1",
                        observation_cutoff=AT - timedelta(days=2),
                        label="success",
                    ),
                    LearningObservation(
                        observation_id="failure",
                        feature_snapshot_id="feature-1",
                        outcome_id=failure.id,
                        route_id="route-1",
                        observation_cutoff=AT - timedelta(days=1),
                        label="failure",
                    ),
                ],
            )
        )
    dataset = LearningDatasetService(session).build(
        LearningDatasetBuildRequest(
            dataset_key="routes",
            idempotency_key="dataset-1",
            observations=[
                LearningObservation(
                    observation_id="a",
                    outcome_id=success.id,
                    route_id="route-1",
                    feature_snapshot_id="feature-0",
                    observation_cutoff=AT - timedelta(days=1),
                    label="success",
                ),
                LearningObservation(
                    observation_id="b",
                    outcome_id=failure.id,
                    route_id="route-1",
                    feature_snapshot_id="feature-1",
                    observation_cutoff=AT - timedelta(days=1),
                    label="failure",
                    human_intervention=True,
                ),
                LearningObservation(
                    observation_id="c",
                    outcome_id=no_reply.id,
                    route_id="route-1",
                    feature_snapshot_id="feature-2",
                    observation_cutoff=AT - timedelta(days=1),
                    label="no_reply",
                    exploration_marker=True,
                ),
            ],
        )
    )
    assert dataset.label_counts_json == {"success": 1, "failure": 1, "no_reply": 1}
    assert len(LearningDatasetService(session).items(dataset.id)) == 3


def test_evaluation_requires_better_calibration_and_safety(session):
    dataset = LearningDatasetRow(
        id="dataset-eval",
        dataset_key="eval",
        dataset_version=1,
        idempotency_key="dataset-eval-key",
        request_hash="1" * 64,
        feature_schema_version="v1",
        row_count=4,
        label_counts_json={"success": 2, "failure": 2, "no_reply": 0},
        status="immutable",
    )
    session.add(dataset)
    for index in range(4):
        session.add(
            LearningDatasetItemRow(
                id=f"eval-item-{index}",
                dataset_id=dataset.id,
                observation_id=f"obs-{index}",
                observation_cutoff=AT,
                feature_snapshot_id=f"feature-{index}",
                feature_snapshot_json={},
                feature_as_of=AT,
                source_max_available_at=AT,
                label="success" if index % 2 else "failure",
                human_intervention=False,
                exploration_marker=False,
            )
        )
    session.commit()
    report = EvaluationService(session).evaluate(
        EvaluationRequest(
            dataset_id=dataset.id,
            idempotency_key="eval-1",
            evaluated_at=AT,
            training_cutoff=AT - timedelta(days=30),
            validation_start=AT - timedelta(days=10),
            validation_end=AT,
            baseline_predictions=[0.7, 0.7, 0.7, 0.7],
            challenger_predictions=[0.1, 0.9, 0.1, 0.9],
            labels=[False, True, False, True],
            economic={"baseline": 1, "challenger": 2},
            safety={"checks": {"loss_limit": True, "pii": True}},
            slices=[{"name": "no_reply", "predictions": [0.1, 0.2], "labels": [False, False]}],
        )
    )
    assert report.eligible
    assert report.challenger_json["brier_score"] < report.baseline_json["brier_score"]
    unsafe = EvaluationService(session).evaluate(
        EvaluationRequest(
            dataset_id=dataset.id,
            idempotency_key="eval-unsafe",
            evaluated_at=AT,
            training_cutoff=AT - timedelta(days=30),
            validation_start=AT - timedelta(days=10),
            validation_end=AT,
            baseline_predictions=[0.5, 0.5, 0.5, 0.5],
            challenger_predictions=[0.1, 0.9, 0.1, 0.9],
            labels=[False, True, False, True],
            safety={"checks": {"loss_limit": False}},
        )
    )
    assert not unsafe.eligible


def test_reviews_are_pending_and_dashboard_has_separate_kpis(session):
    proposal = ReviewProposalService(session).propose(
        ReviewProposalRequest(
            idempotency_key="proposal-1",
            proposal_type="policy",
            subject_ref="route-stage",
            proposal={"change": "require qualification"},
            evidence_refs=["evaluation:eval-1"],
            created_by="system",
        )
    )
    assert proposal.status == "review_pending"
    with pytest.raises(PermissionError):
        ReviewProposalService(session).apply(proposal.id)
    realized = outcome(session)
    invoice = InvoiceRefRow(
        id="invoice-1",
        idempotency_key="invoice-key",
        request_hash="2" * 64,
        order_id="order-1",
        invoice_kind="sales",
        invoice_ref="INV-1",
        amount=100,
        currency="USD",
        invoice_date=AT.date(),
        evidence_refs_json=[],
        source_system="fixture",
        normalized_amount=100,
        normalized_currency="USD",
        status="issued",
    )
    session.add(invoice)
    session.commit()
    dashboard = DashboardService(session).snapshot(
        DashboardSnapshotRequest(
            snapshot_key="weekly",
            idempotency_key="dashboard-1",
            as_of=AT,
            invoice_ids=[invoice.id],
            pnl_snapshot_ids=[realized.pnl_snapshot_id],
            outcome_ids=[realized.id],
        )
    )
    assert dashboard.sales_json["gross_sales"] == "100"
    assert dashboard.contribution_json["contribution_pnl"] == "50.0000"
    assert DashboardService(session).latest("weekly").id == dashboard.id
    with pytest.raises(LookupError, match="was not found"):
        DashboardService(session).latest("missing")
    with pytest.raises(ValueError, match="immutable execution fact"):
        DashboardService(session).snapshot(
            DashboardSnapshotRequest(
                snapshot_key="empty",
                idempotency_key="dashboard-empty",
                as_of=AT,
            )
        )
