from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from deal_helpers import create_action, create_experiment

from tradefoundry.tradealpha.contracts import (
    ActionOutcomeScenario,
    ActionValuationRequest,
    CashflowDistributionRequest,
    FeatureSnapshotRequest,
    LossDistribution,
    ProbabilityEstimateRequest,
    RouteValuationRequest,
    TriangularCashflow,
)
from tradefoundry.tradealpha.features import FeatureRegistryService, FeatureSnapshotService
from tradefoundry.tradealpha.probability import ProbabilityService
from tradefoundry.tradealpha.valuation import (
    ActionValuationService,
    CashflowService,
    RouteValuationService,
)


def _cashflow_request(key: str, at: datetime, seed: int = 7):
    zero_loss = LossDistribution(
        probability=0,
        severity=TriangularCashflow(low=0, mode=0, high=0, at=at + timedelta(days=30)),
    )
    return CashflowDistributionRequest(
        idempotency_key=key,
        valuation_at=at,
        currency="USD",
        discount_rate=0.1,
        revenue=TriangularCashflow(low=1000, mode=1200, high=1500, at=at + timedelta(days=60)),
        variable_cost=TriangularCashflow(low=300, mode=400, high=500, at=at + timedelta(days=30)),
        credit_loss=zero_loss,
        quality_loss=zero_loss,
        compliance_loss=zero_loss,
        sample_count=500,
        seed=seed,
    )


def test_probability_chain_has_wide_interval_for_small_data(session, deal_route_factory):
    _, route = deal_route_factory()
    result = ProbabilityService(session).estimate(
        route.id,
        ProbabilityEstimateRequest(
            idempotency_key="probability-small-data", as_of=datetime.now(UTC) + timedelta(seconds=1)
        ),
    )
    assert len(result.stages_json) == 5
    assert result.overall_low < result.overall_mean < result.overall_high
    assert result.overall_high - result.overall_low > 0.01


def test_probability_replay_is_seed_deterministic(session, deal_route_factory):
    _, route = deal_route_factory()
    at = datetime.now(UTC) + timedelta(seconds=1)
    one = ProbabilityService(session).estimate(
        route.id, ProbabilityEstimateRequest(idempotency_key="prob-one", as_of=at, seed=42)
    )
    two = ProbabilityService(session).estimate(
        route.id, ProbabilityEstimateRequest(idempotency_key="prob-two", as_of=at, seed=42)
    )
    assert (one.overall_mean, one.overall_low, one.overall_high) == (
        two.overall_mean,
        two.overall_low,
        two.overall_high,
    )


def test_probability_records_visible_cohort_fallback(session, deal_route_factory):
    _, route = deal_route_factory()
    FeatureRegistryService(session).seed_defaults()
    at = datetime.now(UTC) + timedelta(seconds=1)
    snapshot = FeatureSnapshotService(session).materialize(
        route.id,
        FeatureSnapshotRequest(idempotency_key="probability-features", as_of=at),
    )
    result = ProbabilityService(session).estimate(
        route.id,
        ProbabilityEstimateRequest(
            idempotency_key="probability-sliced",
            as_of=at,
            feature_snapshot_id=snapshot.id,
        ),
    )
    assert result.context_json["cohort_scope"] == "portfolio_fallback"


def test_cashflow_monte_carlo_is_deterministic_and_bounded(session, deal_route_factory):
    _, route = deal_route_factory()
    at = datetime.now(UTC) + timedelta(seconds=1)
    one = CashflowService(session).simulate(route.id, _cashflow_request("cash-one", at, 77))
    two = CashflowService(session).simulate(route.id, _cashflow_request("cash-two", at, 77))
    assert one.metrics_json == two.metrics_json
    assert one.metrics_json["worst_case"] <= one.metrics_json["p50"]
    assert one.metrics_json["p50"] <= one.metrics_json["best_case"]


def test_cashflow_rejects_past_business_time(session, deal_route_factory):
    _, route = deal_route_factory()
    at = datetime.now(UTC) + timedelta(days=3)
    request = _cashflow_request("cash-past", at)
    request.revenue.at = at - timedelta(seconds=1)
    with pytest.raises(ValueError, match="cannot precede"):
        CashflowService(session).simulate(route.id, request)


def test_route_and_action_value_separate_sunk_cost_and_negative_voi(session, deal_route_factory):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    action = create_action(session, experiment.id, cost="100.00")
    at = datetime.now(UTC) + timedelta(seconds=1)
    probability = ProbabilityService(session).estimate(
        route.id, ProbabilityEstimateRequest(idempotency_key="value-prob", as_of=at)
    )
    cashflow = CashflowService(session).simulate(route.id, _cashflow_request("value-cash", at))
    route_value = RouteValuationService(session).value(
        route.id,
        RouteValuationRequest(
            idempotency_key="route-value",
            probability_estimate_id=probability.id,
            cashflow_distribution_id=cashflow.id,
            as_of=at,
            peak_working_capital=Decimal("500"),
            attention_hours=Decimal("2"),
            attention_hourly_cost=Decimal("20"),
        ),
    )
    action_value = ActionValuationService(session).value(
        action.id,
        ActionValuationRequest(
            idempotency_key="action-value",
            route_valuation_id=route_value.id,
            as_of=at,
            attention_cost=Decimal("20"),
            legal_reputation_risk_cost=Decimal("10"),
            outcomes=[
                ActionOutcomeScenario(
                    outcome_key="success",
                    probability=0.5,
                    post_action_route_value=Decimal("-500"),
                ),
                ActionOutcomeScenario(
                    outcome_key="failure",
                    probability=0.5,
                    post_action_route_value=Decimal("-600"),
                ),
            ],
        ),
    )
    assert route_value.sunk_cost == Decimal("0.0000")
    assert route_value.future_avoidable_cost > 0
    assert action_value.net_voi < 0 and action_value.recommended is False
