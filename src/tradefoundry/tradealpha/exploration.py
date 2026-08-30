from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.models import ActionRow, DealRouteRow
from tradefoundry.tradealpha.common import idempotent_row, money, request_fingerprint
from tradefoundry.tradealpha.contracts import (
    ExplorationRequest,
    ExplorationResult,
    ExplorationRunView,
    ExplorationSelectionView,
)
from tradefoundry.tradealpha.models import (
    AllocationRunRow,
    ExplorationRunRow,
    ExplorationSelectionRow,
    ModelVersionRow,
)


class ExplorationService:
    def __init__(self, session: Session):
        self.session = session

    def select(self, request: ExplorationRequest) -> ExplorationResult:
        request_hash = request_fingerprint({}, request)
        existing = idempotent_row(
            self.session, ExplorationRunRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            rows = self.session.scalars(
                select(ExplorationSelectionRow)
                .where(ExplorationSelectionRow.run_id == existing.id)
                .order_by(ExplorationSelectionRow.rank)
            ).all()
            return ExplorationResult(
                run=ExplorationRunView.model_validate(existing),
                selections=[ExplorationSelectionView.model_validate(row) for row in rows],
            )
        if (
            request.allocation_run_id
            and self.session.get(AllocationRunRow, request.allocation_run_id) is None
        ):
            raise LookupError(f"allocation run {request.allocation_run_id} not found")
        if (
            request.model_version_id
            and self.session.get(ModelVersionRow, request.model_version_id) is None
        ):
            raise LookupError(f"model version {request.model_version_id} not found")
        for candidate in request.candidates:
            if candidate.currency != request.currency:
                raise ValueError("exploration candidate currencies must match the run")
            route = self.session.get(DealRouteRow, candidate.route_id)
            action = self.session.get(ActionRow, candidate.action_id)
            if route is None or action is None or action.route_id != candidate.route_id:
                raise LookupError("exploration candidate route/action pair does not exist")
        reasons = []
        budget = money(request.total_budget * Decimal(str(request.max_exploration_rate)))
        status = "enabled"
        if request.outcome_count < request.minimum_outcomes:
            status = "disabled"
            reasons.append("insufficient_outcomes_for_controlled_exploration")
        eligible = [
            item
            for item in request.candidates
            if item.policy_clear and item.risk_tier in {"low", "normal"}
        ]
        excluded = len(request.candidates) - len(eligible)
        if excluded:
            reasons.append(f"excluded_{excluded}_policy_or_high_risk_candidates")
        rng = np.random.default_rng(request.seed)
        ordered = [eligible[index] for index in rng.permutation(len(eligible))] if eligible else []
        selected = []
        remaining = budget
        if status == "enabled":
            for candidate in ordered:
                if candidate.amount <= remaining:
                    selected.append(candidate)
                    remaining -= candidate.amount
        run = ExplorationRunRow(
            id=str(uuid4()),
            allocation_run_id=request.allocation_run_id,
            model_version_id=request.model_version_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            total_budget=money(request.total_budget),
            max_exploration_rate=request.max_exploration_rate,
            exploration_budget=budget,
            seed=request.seed,
            outcome_count=request.outcome_count,
            minimum_outcomes=request.minimum_outcomes,
            status=status,
            reasons_json=reasons,
        )
        self.session.add(run)
        rows = []
        propensity = min(1.0, len(selected) / len(eligible)) if eligible else 0.0
        for rank, candidate in enumerate(selected, 1):
            row = ExplorationSelectionRow(
                id=str(uuid4()),
                run_id=run.id,
                route_id=candidate.route_id,
                action_id=candidate.action_id,
                amount=money(candidate.amount),
                propensity=propensity,
                rank=rank,
                reason="seeded_uniform_exploration_within_policy_and_risk_boundary",
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return ExplorationResult(
            run=ExplorationRunView.model_validate(run),
            selections=[ExplorationSelectionView.model_validate(row) for row in rows],
        )
