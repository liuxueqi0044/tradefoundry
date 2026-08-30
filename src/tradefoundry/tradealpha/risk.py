from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.models import ActionRow, DealRouteRow
from tradefoundry.tradealpha.common import idempotent_row, money, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    PortfolioAssessmentRequest,
    PortfolioAssessmentView,
    PortfolioCandidate,
    RiskLimitSetCreate,
    RiskLimitSetView,
)
from tradefoundry.tradealpha.models import PortfolioAssessmentRow, RiskLimitSetRow


def _decimal_limits(limits: dict) -> dict:
    return {
        key: (
            {item: Decimal(str(value)) for item, value in values.items()}
            if isinstance(values, dict)
            else Decimal(str(values))
        )
        for key, values in limits.items()
    }


def evaluate_limits(candidates: list[PortfolioCandidate], limit_row: RiskLimitSetRow):
    limits = _decimal_limits(limit_row.limits_json)
    exposure: dict[str, dict[str, Decimal]] = {
        key: defaultdict(Decimal)
        for key in ["country", "buyer", "product", "currency", "correlation_group"]
    }
    unsecured = Decimal(0)
    total = Decimal(0)
    for candidate in candidates:
        total += candidate.amount
        exposure["country"][candidate.country_code] += candidate.amount
        exposure["buyer"][candidate.buyer_id] += candidate.amount
        exposure["product"][candidate.product_id] += candidate.amount
        exposure["currency"][candidate.currency] += candidate.amount
        exposure["correlation_group"][candidate.correlation_group] += candidate.amount
        unsecured += candidate.unsecured_credit
    violations = []
    if total > limit_row.total_budget:
        violations.append(
            {
                "dimension": "total_budget",
                "key": "portfolio",
                "exposure": str(total),
                "limit": str(limit_row.total_budget),
            }
        )
    for dimension, configured in limits.items():
        if dimension == "unsecured_credit":
            if unsecured > configured:
                violations.append(
                    {
                        "dimension": dimension,
                        "key": "portfolio",
                        "exposure": str(unsecured),
                        "limit": str(configured),
                    }
                )
            continue
        for key, cap in configured.items():
            value = exposure[dimension].get(key, Decimal(0))
            if value > cap:
                violations.append(
                    {
                        "dimension": dimension,
                        "key": key,
                        "exposure": str(value),
                        "limit": str(cap),
                    }
                )
    marginal = []
    for dimension, configured in limits.items():
        if dimension == "unsecured_credit":
            marginal.append(
                {
                    "dimension": dimension,
                    "key": "portfolio",
                    "exposure": str(unsecured),
                    "headroom": str(configured - unsecured),
                }
            )
            continue
        for key, cap in configured.items():
            value = exposure[dimension].get(key, Decimal(0))
            marginal.append(
                {
                    "dimension": dimension,
                    "key": key,
                    "exposure": str(value),
                    "headroom": str(cap - value),
                }
            )
    return violations, marginal


class RiskLimitService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: RiskLimitSetCreate) -> RiskLimitSetView:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, RiskLimitSetRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return RiskLimitSetView.model_validate(existing)
        version = self.session.scalar(
            select(func.coalesce(func.max(RiskLimitSetRow.version_no), 0)).where(
                RiskLimitSetRow.limit_key == request.limit_key
            )
        )
        self.session.execute(
            update(RiskLimitSetRow)
            .where(
                RiskLimitSetRow.limit_key == request.limit_key,
                RiskLimitSetRow.status == "active",
            )
            .values(status="deprecated")
        )
        row = RiskLimitSetRow(
            id=str(uuid4()),
            limit_key=request.limit_key,
            version_no=int(version) + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            currency=request.currency,
            total_budget=money(request.amount),
            limits_json=request.limits.model_dump(mode="json"),
            status="active",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return RiskLimitSetView.model_validate(row)

    def get(self, limit_set_id: str) -> RiskLimitSetView:
        row = self.session.get(RiskLimitSetRow, limit_set_id)
        if row is None:
            raise LookupError(f"risk limit set {limit_set_id} not found")
        return RiskLimitSetView.model_validate(row)

    def assess(
        self, limit_set_id: str, request: PortfolioAssessmentRequest
    ) -> PortfolioAssessmentView:
        request_hash = request_fingerprint({"limit_set_id": limit_set_id}, request)
        existing = idempotent_row(
            self.session, PortfolioAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return PortfolioAssessmentView.model_validate(existing)
        limit_row = self.session.get(RiskLimitSetRow, limit_set_id)
        if limit_row is None:
            raise LookupError(f"risk limit set {limit_set_id} not found")
        self._validate_candidates(limit_row, request.candidates)
        violations, marginal = evaluate_limits(request.candidates, limit_row)
        row = PortfolioAssessmentRow(
            id=str(uuid4()),
            limit_set_id=limit_set_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            candidates_json=[item.model_dump(mode="json") for item in request.candidates],
            feasible=not violations,
            violations_json=violations,
            marginal_risk_json=marginal,
        )
        self.session.add(row)
        self.session.commit()
        return PortfolioAssessmentView.model_validate(row)

    def _validate_candidates(
        self, limit_row: RiskLimitSetRow, candidates: list[PortfolioCandidate]
    ) -> None:
        action_ids = set()
        for candidate in candidates:
            if candidate.currency != limit_row.currency:
                raise ValueError("all candidates must use the limit-set currency")
            if candidate.action_id in action_ids:
                raise ValueError("candidate action IDs must be unique")
            action_ids.add(candidate.action_id)
            route = self.session.get(DealRouteRow, candidate.route_id)
            action = self.session.get(ActionRow, candidate.action_id)
            if route is None or action is None or action.route_id != route.id:
                raise LookupError("candidate route/action pair does not exist")
