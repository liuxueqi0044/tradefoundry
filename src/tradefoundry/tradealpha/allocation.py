from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.tradealpha.common import idempotent_row, money, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    AllocationRequest,
    AllocationResult,
    AllocationRunView,
    AllocationView,
)
from tradefoundry.tradealpha.models import AllocationRow, AllocationRunRow, RiskLimitSetRow
from tradefoundry.tradealpha.risk import RiskLimitService, evaluate_limits


class AllocationService:
    OBJECTIVE_VERSION = "hard-limits-greedy-v1"

    def __init__(self, session: Session):
        self.session = session

    def allocate(self, limit_set_id: str, request: AllocationRequest) -> AllocationResult:
        request_hash = request_fingerprint({"limit_set_id": limit_set_id}, request)
        existing = idempotent_row(
            self.session, AllocationRunRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            rows = self.session.scalars(
                select(AllocationRow)
                .where(AllocationRow.run_id == existing.id)
                .order_by(AllocationRow.rank)
            ).all()
            return AllocationResult(
                run=AllocationRunView.model_validate(existing),
                allocations=[AllocationView.model_validate(row) for row in rows],
            )
        limits = self.session.get(RiskLimitSetRow, limit_set_id)
        if limits is None:
            raise LookupError(f"risk limit set {limit_set_id} not found")
        if limits.status != "active":
            raise ValueError("allocation requires an active risk limit set")
        if request.currency != limits.currency:
            raise ValueError("allocation and risk-limit currencies must match")
        RiskLimitService(self.session)._validate_candidates(limits, request.candidates)
        effective_budget = min(request.budget, limits.total_budget)
        selected = []
        results = []
        total = Decimal(0)
        ordered = sorted(request.candidates, key=lambda item: (-item.score, item.action_id))
        for rank, candidate in enumerate(ordered, 1):
            reasons = []
            status = "selected"
            if not candidate.policy_clear:
                status = "excluded"
                reasons.append("policy_not_clear")
            elif candidate.risk_tier == "critical":
                status = "excluded"
                reasons.append("critical_risk")
            elif total + candidate.amount > effective_budget:
                status = "restricted"
                reasons.append("portfolio_budget_limit")
            else:
                violations, _ = evaluate_limits([*selected, candidate], limits)
                if violations:
                    status = "restricted"
                    reasons.extend(f"{item['dimension']}:{item['key']}" for item in violations)
            allocated = candidate.amount if status == "selected" else Decimal(0)
            if allocated:
                selected.append(candidate)
                total += allocated
            results.append((rank, candidate, status, reasons, allocated))
        run = AllocationRunRow(
            id=str(uuid4()),
            limit_set_id=limit_set_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            budget=money(request.budget),
            currency=request.currency,
            objective_version=self.OBJECTIVE_VERSION,
            status="completed",
            candidates_json=[item.model_dump(mode="json") for item in ordered],
            total_allocated=money(total),
            metrics_json={
                "candidate_count": len(ordered),
                "selected_count": len(selected),
                "restricted_count": sum(item[2] == "restricted" for item in results),
                "excluded_count": sum(item[2] == "excluded" for item in results),
                "unused_budget": str(money(effective_budget - total)),
            },
        )
        self.session.add(run)
        rows = []
        for rank, candidate, status, reasons, allocated in results:
            row = AllocationRow(
                id=str(uuid4()),
                run_id=run.id,
                route_id=candidate.route_id,
                action_id=candidate.action_id,
                rank=rank,
                requested_amount=money(candidate.amount),
                allocated_amount=money(allocated),
                status=status,
                score=candidate.score,
                reasons_json=reasons,
                exposure_json={
                    "country": candidate.country_code,
                    "buyer": candidate.buyer_id,
                    "product": candidate.product_id,
                    "currency": candidate.currency,
                    "correlation_group": candidate.correlation_group,
                    "unsecured_credit": str(candidate.unsecured_credit),
                },
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return AllocationResult(
            run=AllocationRunView.model_validate(run),
            allocations=[AllocationView.model_validate(row) for row in rows],
        )
