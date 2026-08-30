from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.models import ActionRow, BudgetSpendRow, DealRouteRow
from tradefoundry.tradealpha.common import aware, idempotent_row, money, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    ActionValuationRequest,
    ActionValuationView,
    CashflowDistributionRequest,
    CashflowDistributionView,
    RouteValuationRequest,
    RouteValuationView,
)
from tradefoundry.tradealpha.models import (
    ActionValuationRow,
    CashflowDistributionRow,
    ProbabilityEstimateRow,
    RouteValuationRow,
)


class CashflowService:
    def __init__(self, session: Session):
        self.session = session

    def simulate(
        self, route_id: str, request: CashflowDistributionRequest
    ) -> CashflowDistributionView:
        request_hash = request_fingerprint({"route_id": route_id}, request)
        existing = idempotent_row(
            self.session, CashflowDistributionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return CashflowDistributionView.model_validate(existing)
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        if route.currency != request.currency:
            raise ValueError("cashflow currency must match the route currency")
        flows = [
            request.revenue,
            request.variable_cost,
            request.credit_loss.severity,
            request.quality_loss.severity,
            request.compliance_loss.severity,
        ]
        if any(flow.at < request.valuation_at for flow in flows):
            raise ValueError("future cashflows cannot precede valuation_at")
        rng = np.random.default_rng(request.seed)
        count = request.sample_count

        def triangular(flow):
            if flow.low == flow.high:
                values = np.full(count, float(flow.low))
            else:
                values = rng.triangular(float(flow.low), float(flow.mode), float(flow.high), count)
            years = (flow.at - request.valuation_at).total_seconds() / (365.25 * 86400)
            return values / ((1 + request.discount_rate) ** years)

        revenue = triangular(request.revenue)
        variable_cost = triangular(request.variable_cost)

        def stochastic_loss(loss):
            severity = triangular(loss.severity)
            return severity * (rng.random(count) < loss.probability)

        losses = (
            stochastic_loss(request.credit_loss)
            + stochastic_loss(request.quality_loss)
            + stochastic_loss(request.compliance_loss)
        )
        before_avoidable = revenue - losses
        net = before_avoidable - variable_cost
        metrics = {
            "conditional_npv_before_avoidable_mean": float(before_avoidable.mean()),
            "future_avoidable_cost_mean": float(variable_cost.mean()),
            "mean": float(net.mean()),
            "p10": float(np.quantile(net, 0.1)),
            "p50": float(np.quantile(net, 0.5)),
            "p90": float(np.quantile(net, 0.9)),
            "best_case": float(net.max()),
            "worst_case": float(net.min()),
            "loss_probability": float((net < 0).mean()),
        }
        row = CashflowDistributionRow(
            id=str(uuid4()),
            route_id=route_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            valuation_at=request.valuation_at,
            currency=request.currency,
            discount_rate=request.discount_rate,
            sample_count=request.sample_count,
            seed=request.seed,
            inputs_json=request.model_dump(mode="json"),
            metrics_json=metrics,
            calculator_version="triangular-npv-mc-v1",
        )
        self.session.add(row)
        self.session.commit()
        return CashflowDistributionView.model_validate(row)


class RouteValuationService:
    def __init__(self, session: Session):
        self.session = session

    def value(self, route_id: str, request: RouteValuationRequest) -> RouteValuationView:
        request_hash = request_fingerprint({"route_id": route_id}, request)
        existing = idempotent_row(
            self.session, RouteValuationRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return RouteValuationView.model_validate(existing)
        probability = self.session.get(ProbabilityEstimateRow, request.probability_estimate_id)
        cashflow = self.session.get(CashflowDistributionRow, request.cashflow_distribution_id)
        if probability is None or probability.route_id != route_id:
            raise LookupError("probability estimate does not exist for this route")
        if cashflow is None or cashflow.route_id != route_id:
            raise LookupError("cashflow distribution does not exist for this route")
        if aware(probability.as_of) > request.as_of or aware(cashflow.valuation_at) > request.as_of:
            raise ValueError("valuation as_of cannot precede its inputs")
        action_ids = self.session.scalars(
            select(ActionRow.id).where(
                ActionRow.route_id == route_id, ActionRow.created_at <= request.as_of
            )
        ).all()
        sunk = Decimal(0)
        if action_ids:
            sunk = sum(
                self.session.scalars(
                    select(BudgetSpendRow.amount).where(
                        BudgetSpendRow.action_id.in_(action_ids),
                        BudgetSpendRow.created_at <= request.as_of,
                    )
                ).all(),
                Decimal(0),
            )
        future_cost = money(cashflow.metrics_json["future_avoidable_cost_mean"])
        attention = money(request.attention_hours * request.attention_hourly_cost)
        before_cost = money(cashflow.metrics_json["conditional_npv_before_avoidable_mean"])
        continuation = money(
            Decimal(str(probability.overall_mean)) * before_cost - future_cost - attention
        )
        total = money(continuation - sunk)
        capital_base = request.peak_working_capital + attention
        efficiency = float(continuation / capital_base) if capital_base else 0.0
        row = RouteValuationRow(
            id=str(uuid4()),
            route_id=route_id,
            probability_estimate_id=probability.id,
            cashflow_distribution_id=cashflow.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            currency=cashflow.currency,
            sunk_cost=money(sunk),
            future_avoidable_cost=future_cost,
            attention_cost=attention,
            peak_working_capital=money(request.peak_working_capital),
            continuation_value=continuation,
            total_economic_value=total,
            capital_efficiency=efficiency,
            risk_metrics_json={
                **cashflow.metrics_json,
                "collection_probability": probability.overall_mean,
                "probability_low": probability.overall_low,
                "probability_high": probability.overall_high,
            },
            assumptions_json=[
                "Sunk cost is reported separately and does not affect the continue/stop decision.",
                "Future variable cost remains avoidable until the modeled cashflow date.",
            ],
        )
        self.session.add(row)
        self.session.commit()
        return RouteValuationView.model_validate(row)


class ActionValuationService:
    def __init__(self, session: Session):
        self.session = session

    def value(self, action_id: str, request: ActionValuationRequest) -> ActionValuationView:
        request_hash = request_fingerprint({"action_id": action_id}, request)
        existing = idempotent_row(
            self.session, ActionValuationRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ActionValuationView.model_validate(existing)
        action = self.session.get(ActionRow, action_id)
        route_value = self.session.get(RouteValuationRow, request.route_valuation_id)
        if action is None:
            raise LookupError(f"action {action_id} not found")
        if route_value is None or route_value.route_id != action.route_id:
            raise LookupError("route valuation does not exist for this action's route")
        if action.currency != route_value.currency:
            raise ValueError("action and route valuation currencies must match")
        if aware(route_value.as_of) > request.as_of:
            raise ValueError("action valuation as_of cannot precede route valuation")
        expected = sum(
            Decimal(str(item.probability)) * item.post_action_route_value
            for item in request.outcomes
        )
        cash_cost = action.estimated_cost
        net_voi = money(
            expected
            - route_value.continuation_value
            - cash_cost
            - request.attention_cost
            - request.legal_reputation_risk_cost
        )
        total_cost = cash_cost + request.attention_cost + request.legal_reputation_risk_cost
        priority = float(net_voi / total_cost) if total_cost else float(net_voi)
        row = ActionValuationRow(
            id=str(uuid4()),
            action_id=action_id,
            route_valuation_id=route_value.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            currency=route_value.currency,
            action_cash_cost=money(cash_cost),
            attention_cost=money(request.attention_cost),
            risk_cost=money(request.legal_reputation_risk_cost),
            expected_post_action_value=money(expected),
            net_voi=net_voi,
            priority_score=priority,
            recommended=net_voi > 0 and action.policy_status in {"not_required", "approved"},
            outcomes_json=[item.model_dump(mode="json") for item in request.outcomes],
        )
        self.session.add(row)
        self.session.commit()
        return ActionValuationView.model_validate(row)
