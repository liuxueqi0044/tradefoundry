from datetime import UTC, datetime, timedelta
from decimal import Decimal

from deal_helpers import create_action, create_experiment

from tradefoundry.tradealpha.allocation import AllocationService
from tradefoundry.tradealpha.contracts import (
    AllocationRequest,
    PortfolioAssessmentRequest,
    PortfolioCandidate,
    RiskLimits,
    RiskLimitSetCreate,
)
from tradefoundry.tradealpha.risk import RiskLimitService


def _limit_set(session, key="limits-v1"):
    return RiskLimitService(session).create(
        RiskLimitSetCreate(
            limit_key="primary",
            idempotency_key=key,
            amount=Decimal("200"),
            currency="USD",
            limits=RiskLimits(
                country={"KE": Decimal("150")},
                buyer={"buyer-1": Decimal("100")},
                product={"product-1": Decimal("180")},
                currency={"USD": Decimal("200")},
                correlation_group={"group-1": Decimal("120")},
                unsecured_credit=Decimal("80"),
            ),
            created_by="risk-owner",
        )
    )


def _candidate(route, action, amount, score, **changes):
    values = {
        "route_id": route.id,
        "action_id": action.id,
        "amount": Decimal(amount),
        "currency": "USD",
        "score": score,
        "country_code": "KE",
        "buyer_id": "buyer-1",
        "product_id": "product-1",
        "correlation_group": "group-1",
        "unsecured_credit": Decimal("10"),
        "policy_clear": True,
        "risk_tier": "normal",
    }
    values.update(changes)
    return PortfolioCandidate(**values)


def test_portfolio_assessment_reports_explicit_limit_violation(session, deal_route_factory):
    _, route = deal_route_factory()
    action = create_action(session, create_experiment(session, route.id).id)
    limits = _limit_set(session)
    result = RiskLimitService(session).assess(
        limits.id,
        PortfolioAssessmentRequest(
            idempotency_key="portfolio-over-limit",
            as_of=datetime.now(UTC) + timedelta(seconds=1),
            candidates=[_candidate(route, action, "130", 90)],
        ),
    )
    assert result.feasible is False
    assert {item["dimension"] for item in result.violations_json} >= {
        "buyer",
        "correlation_group",
    }


def test_portfolio_assessment_exposes_headroom(session, deal_route_factory):
    _, route = deal_route_factory()
    action = create_action(session, create_experiment(session, route.id).id)
    limits = _limit_set(session)
    result = RiskLimitService(session).assess(
        limits.id,
        PortfolioAssessmentRequest(
            idempotency_key="portfolio-headroom",
            as_of=datetime.now(UTC) + timedelta(seconds=1),
            candidates=[_candidate(route, action, "50", 80)],
        ),
    )
    assert result.feasible is True
    buyer = next(
        item
        for item in result.marginal_risk_json
        if item["dimension"] == "buyer" and item["key"] == "buyer-1"
    )
    assert Decimal(buyer["headroom"]) == Decimal("50")


def test_allocator_restricts_high_score_when_hard_limit_would_break(session, deal_route_factory):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    high = create_action(session, experiment.id, key="high")
    next_best = create_action(session, experiment.id, key="next")
    limits = _limit_set(session)
    result = AllocationService(session).allocate(
        limits.id,
        AllocationRequest(
            idempotency_key="allocation-hard-limit",
            as_of=datetime.now(UTC) + timedelta(seconds=1),
            budget=Decimal("200"),
            currency="USD",
            candidates=[
                _candidate(route, high, "130", 99),
                _candidate(
                    route,
                    next_best,
                    "80",
                    80,
                    buyer_id="buyer-unlimited",
                    correlation_group="group-unlimited",
                ),
            ],
        ),
    )
    assert result.allocations[0].status == "restricted"
    assert result.allocations[1].status == "selected"
    assert result.run.total_allocated == Decimal("80.0000")


def test_allocator_is_replayable_and_excludes_uncleared_policy(session, deal_route_factory):
    _, route = deal_route_factory()
    action = create_action(session, create_experiment(session, route.id).id)
    limits = _limit_set(session)
    request = AllocationRequest(
        idempotency_key="allocation-replay",
        as_of=datetime.now(UTC) + timedelta(seconds=1),
        budget=Decimal("100"),
        currency="USD",
        candidates=[_candidate(route, action, "20", 100, policy_clear=False)],
    )
    first = AllocationService(session).allocate(limits.id, request)
    second = AllocationService(session).allocate(limits.id, request)
    assert second.run.id == first.run.id
    assert first.allocations[0].status == "excluded"
    assert first.run.total_allocated == Decimal("0.0000")
