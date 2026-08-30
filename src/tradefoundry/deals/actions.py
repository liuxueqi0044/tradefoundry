from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.aggregates import OptimisticLockError
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.contracts import (
    ActionAttemptView,
    ActionCompensationRequest,
    ActionCreate,
    ActionExecutionRequest,
    ActionPolicyUpdate,
    ActionQueueRequest,
    ActionView,
)
from tradefoundry.deals.models import (
    ActionAttemptRow,
    ActionRow,
    DealRouteRow,
    ExperimentRow,
)
from tradefoundry.deals.ports import (
    ActionExecutorPort,
    DenyExternalPolicyPort,
    InternalNoopExecutor,
    PolicyDecisionPort,
)
from tradefoundry.ingestion.hashing import payload_hash


class ActionService:
    def __init__(
        self,
        session: Session,
        *,
        policy_port: PolicyDecisionPort | None = None,
        executor: ActionExecutorPort | None = None,
    ):
        self.session = session
        self.policy_port = policy_port or DenyExternalPolicyPort()
        self.executor = executor or InternalNoopExecutor()

    def create(self, experiment_id: str, request: ActionCreate) -> ActionView:
        experiment = self.session.get(ExperimentRow, experiment_id)
        if experiment is None:
            raise LookupError(f"experiment {experiment_id} not found")
        route = self.session.get(DealRouteRow, experiment.route_id)
        if route is None:
            raise RuntimeError("experiment route is missing")
        if route.lifecycle_status != "active" or experiment.status not in {"planned", "running"}:
            raise ValueError("actions require an active route and open experiment")
        if request.currency != experiment.currency:
            raise ValueError("action and experiment currencies must match")
        if not request.external_side_effect and request.policy_status != "not_required":
            raise ValueError("internal actions must use policy_status=not_required")
        request_hash = payload_hash(
            {"experiment_id": experiment_id, **request.model_dump(mode="json")}
        )
        existing = self.session.scalar(
            select(ActionRow).where(ActionRow.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("action idempotency key was reused with a different payload")
            return ActionView.model_validate(existing)
        dependencies = [
            self.session.get(ActionRow, dependency_id)
            for dependency_id in request.dependency_action_ids
        ]
        if any(
            dependency is None or dependency.route_id != experiment.route_id
            for dependency in dependencies
        ):
            raise ValueError("action dependency is missing or belongs to another route")
        action_id = str(uuid4())
        row = ActionRow(
            id=action_id,
            experiment_id=experiment_id,
            route_id=experiment.route_id,
            action_key=request.action_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            action_type=request.action_type,
            description=request.description,
            external_side_effect=request.external_side_effect,
            estimated_cost=request.amount,
            currency=request.currency,
            policy_decision_ref=request.policy_decision_ref,
            policy_status=request.policy_status,
            payload_json=request.payload,
            dependency_action_ids_json=sorted(set(request.dependency_action_ids)),
            due_at=request.due_at,
            sla_seconds=request.sla_seconds,
            status="proposed",
            external_effect_key=f"deal-action:{action_id}"
            if request.external_side_effect
            else None,
            version=1,
        )
        self.session.add(row)
        self.session.commit()
        return ActionView.model_validate(row)

    def update_policy(self, action_id: str, request: ActionPolicyUpdate) -> ActionView:
        action = self._action(action_id)
        if not action.external_side_effect:
            raise ValueError("internal actions do not accept external policy decisions")
        result = self.session.execute(
            update(ActionRow)
            .where(ActionRow.id == action_id, ActionRow.version == request.expected_version)
            .values(
                policy_status=request.policy_status,
                policy_decision_ref=request.policy_decision_ref,
                version=ActionRow.version + 1,
            )
        )
        if result.rowcount != 1:
            self.session.rollback()
            self._action(action_id)
            raise OptimisticLockError("action version conflict")
        self.session.commit()
        return self.get(action_id)

    def queue(self, action_id: str, request: ActionQueueRequest) -> ActionView:
        action = self._action(action_id)
        if action.status == "queued":
            return ActionView.model_validate(action)
        if action.version != request.expected_version:
            raise OptimisticLockError("action version conflict")
        if action.status not in {"proposed", "blocked", "failed"}:
            raise ValueError(f"action cannot be queued from {action.status}")
        blockers = self.blockers(action)
        if blockers:
            action.status = "blocked"
            action.version += 1
            self.session.commit()
            raise ValueError("action is blocked: " + "; ".join(blockers))
        decision = BudgetService(self.session).authorize(
            action.id, f"budget-queue:{action.id}:v{action.version}"
        )
        if decision.decision != "allow":
            action.status = "blocked"
            action.version += 1
            self.session.commit()
            raise ValueError("action is over budget: " + "; ".join(decision.reasons_json))
        action.status = "queued"
        action.version += 1
        self.session.commit()
        return ActionView.model_validate(action)

    def execute(self, action_id: str, request: ActionExecutionRequest) -> ActionAttemptView:
        action = self._action(action_id)
        if action.status == "succeeded":
            last = self._last_attempt(action.id)
            if last is None:
                raise RuntimeError("succeeded action has no execution attempt")
            return ActionAttemptView.model_validate(last)
        if action.version != request.expected_version:
            raise OptimisticLockError("action version conflict")
        if action.status not in {"queued", "failed"}:
            raise ValueError(f"action cannot execute from {action.status}")
        blockers = self.blockers(action)
        if blockers:
            raise ValueError("action is blocked: " + "; ".join(blockers))
        amount = request.actual_cost if request.actual_cost is not None else action.estimated_cost
        BudgetService(self.session).ensure_spend_allowed(action.id, Decimal(amount))
        attempt_no = (
            int(
                self.session.scalar(
                    select(func.coalesce(func.max(ActionAttemptRow.attempt_no), 0)).where(
                        ActionAttemptRow.action_id == action.id
                    )
                )
                or 0
            )
            + 1
        )
        attempt = ActionAttemptRow(
            id=str(uuid4()),
            action_id=action.id,
            attempt_no=attempt_no,
            status="started",
            executor_name=self.executor.name,
        )
        result = self.session.execute(
            update(ActionRow)
            .where(
                ActionRow.id == action.id,
                ActionRow.version == request.expected_version,
                ActionRow.status.in_({"queued", "failed"}),
            )
            .values(status="executing", version=ActionRow.version + 1)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise OptimisticLockError("action changed concurrently before execution")
        self.session.add(attempt)
        self.session.commit()
        effect_key = action.external_effect_key or f"internal-action:{action.id}"
        try:
            receipt = self.executor.execute(
                action=action,
                external_effect_key=effect_key,
                payload=action.payload_json,
            )
            action.status = "succeeded"
            action.version += 1
            attempt.status = "succeeded"
            attempt.external_receipt_json = receipt
            attempt.completed_at = datetime.now(UTC)
            BudgetService(self.session).record_spend(
                action.id,
                Decimal(amount),
                actor=request.actor,
                external_ref=str(receipt.get("external_ref"))
                if receipt.get("external_ref")
                else None,
            )
        except Exception as exc:
            action.status = "failed"
            action.version += 1
            attempt.status = "failed"
            attempt.error_type = type(exc).__name__
            attempt.error_message = str(exc)
            attempt.completed_at = datetime.now(UTC)
            self.session.commit()
            raise
        return ActionAttemptView.model_validate(attempt)

    def compensate(self, action_id: str, request: ActionCompensationRequest) -> ActionAttemptView:
        action = self._action(action_id)
        if action.version != request.expected_version:
            raise OptimisticLockError("action version conflict")
        if action.status != "succeeded":
            raise ValueError("only a succeeded action can be compensated")
        last_attempt = self._last_attempt(action.id)
        attempt_no = (last_attempt.attempt_no if last_attempt else 0) + 1
        receipt = self.executor.compensate(
            action=action,
            external_effect_key=action.external_effect_key or f"internal-action:{action.id}",
            reason=request.reason,
        )
        attempt = ActionAttemptRow(
            id=str(uuid4()),
            action_id=action.id,
            attempt_no=attempt_no,
            status="compensated",
            executor_name=self.executor.name,
            external_receipt_json=receipt,
            completed_at=datetime.now(UTC),
        )
        action.status = "compensated"
        action.version += 1
        self.session.add(attempt)
        self.session.commit()
        return ActionAttemptView.model_validate(attempt)

    def blockers(self, action: ActionRow) -> list[str]:
        blockers = []
        route = self.session.get(DealRouteRow, action.route_id)
        if route is None:
            blockers.append("action route is missing")
        elif route.lifecycle_status != "active":
            blockers.append(f"route is {route.lifecycle_status}")
        dependencies = [
            self.session.get(ActionRow, dependency_id)
            for dependency_id in action.dependency_action_ids_json
        ]
        incomplete = [
            dependency_id
            for dependency_id, dependency in zip(
                action.dependency_action_ids_json, dependencies, strict=True
            )
            if dependency is None or dependency.status != "succeeded"
        ]
        if incomplete:
            blockers.append("dependencies incomplete: " + ", ".join(incomplete))
        if action.external_side_effect:
            if action.policy_status != "approved" or not action.policy_decision_ref:
                blockers.append("approved PolicyDecision is required")
            elif not self.policy_port.is_approved(action.policy_decision_ref, action):
                blockers.append("PolicyDecision could not be verified")
        return blockers

    def get(self, action_id: str) -> ActionView:
        return ActionView.model_validate(self._action(action_id))

    def list(self, route_id: str) -> list[ActionView]:
        rows = self.session.scalars(
            select(ActionRow)
            .where(ActionRow.route_id == route_id)
            .order_by(ActionRow.due_at, ActionRow.id)
        ).all()
        return [ActionView.model_validate(row) for row in rows]

    def _action(self, action_id: str) -> ActionRow:
        row = self.session.get(ActionRow, action_id)
        if row is None:
            raise LookupError(f"action {action_id} not found")
        return row

    def _last_attempt(self, action_id: str) -> ActionAttemptRow | None:
        return self.session.scalar(
            select(ActionAttemptRow)
            .where(ActionAttemptRow.action_id == action_id)
            .order_by(ActionAttemptRow.attempt_no.desc())
            .limit(1)
        )
