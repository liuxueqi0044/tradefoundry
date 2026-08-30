from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from deal_helpers import create_action, create_experiment

from tradefoundry.tradealpha.analytics import BacktestService, CalibrationService
from tradefoundry.tradealpha.contracts import (
    BacktestLabel,
    BacktestRequest,
    CalibrationPoint,
    CalibrationRequest,
    ExplorationCandidate,
    ExplorationRequest,
    FeatureSnapshotRequest,
    ModelPromotionRequest,
    ModelVersionCreate,
    ScoringPolicyCreate,
)
from tradefoundry.tradealpha.exploration import ExplorationService
from tradefoundry.tradealpha.features import FeatureRegistryService, FeatureSnapshotService
from tradefoundry.tradealpha.registry import ModelRegistryService
from tradefoundry.tradealpha.scoring import ScoringPolicyService


def _policy(session):
    return ScoringPolicyService(session).create(
        ScoringPolicyCreate(
            policy_key="backtest-baseline",
            idempotency_key="backtest-policy-v1",
            name="Backtest baseline",
            weights={"event_reliability": 1, "route_stage_progress": 1},
            created_by="sol",
        )
    )


def test_backtest_compares_alpha_simple_random_and_manual(session, deal_route_factory):
    _, route = deal_route_factory()
    FeatureRegistryService(session).seed_defaults()
    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    snapshot = FeatureSnapshotService(session).materialize(
        route.id,
        FeatureSnapshotRequest(idempotency_key="backtest-features", as_of=cutoff),
    )
    result = BacktestService(session).run(
        _policy(session).id,
        BacktestRequest(
            idempotency_key="valid-backtest",
            cutoff_at=cutoff,
            top_k=1,
            feature_snapshot_ids=[snapshot.id],
            labels=[
                BacktestLabel(
                    route_id=route.id,
                    outcome=True,
                    outcome_available_at=cutoff + timedelta(days=30),
                    manual_baseline_score=10,
                )
            ],
        ),
    )
    assert set(result.metrics_json) == {"alpha", "simple", "random", "manual"}
    assert result.leakage_count == 0


def test_backtest_rejects_outcome_visible_at_cutoff(session, deal_route_factory):
    _, route = deal_route_factory()
    FeatureRegistryService(session).seed_defaults()
    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    snapshot = FeatureSnapshotService(session).materialize(
        route.id,
        FeatureSnapshotRequest(idempotency_key="leak-features", as_of=cutoff),
    )
    with pytest.raises(ValueError, match="temporal leakage"):
        BacktestService(session).run(
            _policy(session).id,
            BacktestRequest(
                idempotency_key="leaking-backtest",
                cutoff_at=cutoff,
                top_k=1,
                feature_snapshot_ids=[snapshot.id],
                labels=[
                    BacktestLabel(
                        route_id=route.id,
                        outcome=True,
                        outcome_available_at=cutoff,
                    )
                ],
            ),
        )


def _calibration_request(key, predictions, minimum=2):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = [
        CalibrationPoint(
            prediction=prediction,
            outcome=outcome,
            prediction_at=start + timedelta(days=index),
            outcome_at=start + timedelta(days=40 + index),
            country_code="KE",
            product_id="product-1",
        )
        for index, (prediction, outcome) in enumerate(predictions)
    ]
    return CalibrationRequest(
        idempotency_key=key,
        evaluated_at=start + timedelta(days=100),
        window_start=start,
        window_end=start + timedelta(days=30),
        points=points,
        minimum_samples=minimum,
        max_brier=0.2,
        max_ece=0.2,
    )


def test_calibration_degradation_forces_rule_fallback(session):
    result = CalibrationService(session).evaluate(
        _calibration_request("bad-calibration", [(0.99, False), (0.98, False)])
    )
    assert result.status == "degraded"
    assert result.recommendation == "fallback_rule_baseline"
    assert result.slices_json


def test_calibration_small_sample_is_not_called_a_model(session):
    result = CalibrationService(session).evaluate(
        _calibration_request("small-calibration", [(0.8, True)], minimum=30)
    )
    assert result.status == "insufficient_data"
    assert result.recommendation == "rule_baseline_only"


def _model_request(key, brier=0.1, safety=True):
    return ModelVersionCreate(
        model_key="conversion-model",
        idempotency_key=key,
        model_type="rule_baseline",
        feature_schema_hash="a" * 64,
        training_data_cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        validation_start=datetime(2025, 2, 1, tzinfo=UTC),
        validation_end=datetime(2025, 3, 1, tzinfo=UTC),
        metrics={"brier_score": brier},
        out_of_time_metrics={"sample_count": 200, "brier_score": brier, "ece": 0.05},
        safety_checks={"no_leakage": safety, "hard_limits_preserved": safety},
        created_by="sol",
    )


def test_model_registry_accepts_only_passing_out_of_time_version(session):
    service = ModelRegistryService(session)
    model = service.register(_model_request("model-good"))
    promotion = service.promote(
        ModelPromotionRequest(
            idempotency_key="promote-good",
            target_model_version_id=model.id,
            actor="sol",
        )
    )
    assert promotion.decision == "accepted"
    assert service.champion("conversion-model").id == model.id


def test_model_registry_rejects_failed_safety_check(session):
    service = ModelRegistryService(session)
    model = service.register(_model_request("model-unsafe", safety=False))
    promotion = service.promote(
        ModelPromotionRequest(
            idempotency_key="promote-unsafe",
            target_model_version_id=model.id,
            actor="sol",
        )
    )
    assert promotion.decision == "rejected"
    assert "safety" in promotion.reasons_json[-1]


def _exploration_candidate(route, action, amount="5", **changes):
    values = {
        "route_id": route.id,
        "action_id": action.id,
        "amount": Decimal(amount),
        "currency": "USD",
        "base_score": 10,
        "policy_clear": True,
        "risk_tier": "normal",
    }
    values.update(changes)
    return ExplorationCandidate(**values)


def test_exploration_disabled_before_outcome_threshold(session, deal_route_factory):
    _, route = deal_route_factory()
    action = create_action(session, create_experiment(session, route.id).id)
    result = ExplorationService(session).select(
        ExplorationRequest(
            idempotency_key="exploration-disabled",
            as_of=datetime.now(UTC) + timedelta(seconds=1),
            total_budget=Decimal("100"),
            currency="USD",
            outcome_count=10,
            minimum_outcomes=100,
            candidates=[_exploration_candidate(route, action)],
        )
    )
    assert result.run.status == "disabled"
    assert result.selections == []


def test_exploration_respects_ten_percent_cap_and_excludes_high_risk(session, deal_route_factory):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    eligible = create_action(session, experiment.id, key="eligible")
    high_risk = create_action(session, experiment.id, key="high-risk")
    result = ExplorationService(session).select(
        ExplorationRequest(
            idempotency_key="exploration-capped",
            as_of=datetime.now(UTC) + timedelta(seconds=1),
            total_budget=Decimal("100"),
            currency="USD",
            max_exploration_rate=0.1,
            outcome_count=100,
            minimum_outcomes=100,
            candidates=[
                _exploration_candidate(route, eligible, "10"),
                _exploration_candidate(route, high_risk, "1", risk_tier="high"),
            ],
        )
    )
    assert sum(item.amount for item in result.selections) <= Decimal("10")
    assert [item.action_id for item in result.selections] == [eligible.id]
