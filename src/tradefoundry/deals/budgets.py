from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.deals.aggregates import OptimisticLockError
from tradefoundry.deals.contracts import (
    BudgetAdjustmentRequest,
    BudgetAdjustmentView,
    BudgetDecisionView,
)
from tradefoundry.deals.models import (
    ActionRow,
    BudgetAdjustmentRow,
    BudgetDecisionRow,
    BudgetReservationRow,
    BudgetSpendRow,
    DealCellRow,
    DealRouteRow,
    ExperimentRow,
)
from tradefoundry.ingestion.hashing import payload_hash


class BudgetService:
    def __init__(self, session: Session):
        self.session = session

    def authorize(self, action_id: str, idempotency_key: str) -> BudgetDecisionView:
        action = self._action(action_id)
        request_hash = payload_hash(
            {
                "action_id": action.id,
                "estimated_cost": str(action.estimated_cost),
                "currency": action.currency,
            }
        )
        existing = self.session.scalar(
            select(BudgetDecisionRow).where(BudgetDecisionRow.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("budget decision key was reused with a different request")
            return BudgetDecisionView.model_validate(existing)
        snapshot = self.snapshot_for_action(action.id, exclude_action_id=action.id)
        reasons = [
            f"{scope} remaining budget is below requested amount"
            for scope, values in snapshot.items()
            if Decimal(values["remaining"]) < action.estimated_cost
        ]
        decision = "deny" if reasons else "allow"
        row = BudgetDecisionRow(
            id=str(uuid4()),
            action_id=action.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            decision=decision,
            requested_amount=action.estimated_cost,
            currency=action.currency,
            remaining_snapshot_json=snapshot,
            reasons_json=reasons,
        )
        self.session.add(row)
        if decision == "allow":
            reservation = self.session.scalar(
                select(BudgetReservationRow).where(BudgetReservationRow.action_id == action.id)
            )
            if reservation is None:
                self.session.add(
                    BudgetReservationRow(
                        id=str(uuid4()),
                        action_id=action.id,
                        amount=action.estimated_cost,
                        currency=action.currency,
                        status="reserved",
                    )
                )
        self.session.commit()
        return BudgetDecisionView.model_validate(row)

    def ensure_spend_allowed(self, action_id: str, amount: Decimal) -> None:
        action = self._action(action_id)
        snapshot = self.snapshot_for_action(action.id, exclude_action_id=action.id)
        blocked = [
            scope for scope, values in snapshot.items() if Decimal(values["remaining"]) < amount
        ]
        if blocked:
            raise ValueError("actual spend exceeds remaining " + ", ".join(blocked) + " budget")

    def record_spend(
        self,
        action_id: str,
        amount: Decimal,
        *,
        actor: str,
        external_ref: str | None = None,
    ) -> BudgetSpendRow:
        action = self._action(action_id)
        existing = self.session.scalar(
            select(BudgetSpendRow).where(BudgetSpendRow.action_id == action_id)
        )
        if existing is not None:
            if existing.amount != amount or existing.currency != action.currency:
                raise ValueError("action spend is immutable and differs from the recorded amount")
            return existing
        self.ensure_spend_allowed(action_id, amount)
        reservation = self.session.scalar(
            select(BudgetReservationRow).where(
                BudgetReservationRow.action_id == action_id,
                BudgetReservationRow.status == "reserved",
            )
        )
        if reservation is None:
            raise ValueError("action has no active budget reservation")
        row = BudgetSpendRow(
            id=str(uuid4()),
            action_id=action_id,
            amount=amount,
            currency=action.currency,
            actor=actor,
            external_ref=external_ref,
        )
        reservation.status = "spent"
        self.session.add(row)
        self.session.commit()
        return row

    def adjust(
        self,
        scope_type: str,
        scope_id: str,
        request: BudgetAdjustmentRequest,
    ) -> BudgetAdjustmentView:
        if scope_type not in {"cell", "route", "experiment"}:
            raise ValueError("budget scope must be cell, route or experiment")
        model = {"cell": DealCellRow, "route": DealRouteRow, "experiment": ExperimentRow}[
            scope_type
        ]
        target = self.session.get(model, scope_id)
        if target is None:
            raise LookupError(f"{scope_type} {scope_id} not found")
        request_hash = payload_hash(
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                **request.model_dump(mode="json"),
            }
        )
        existing = self.session.scalar(
            select(BudgetAdjustmentRow).where(
                BudgetAdjustmentRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("budget adjustment key was reused with a different payload")
            return BudgetAdjustmentView.model_validate(existing)
        if target.version != request.expected_version:
            raise OptimisticLockError(f"{scope_type} version conflict")
        if target.currency != request.currency:
            raise ValueError("budget adjustment currency must match the scope")
        floor = self._scope_floor(scope_type, scope_id)
        if request.amount < floor:
            raise ValueError(f"new budget is below committed or allocated amount {floor}")
        ceiling = self._scope_ceiling(scope_type, target)
        if ceiling is not None and request.amount > ceiling:
            raise ValueError(f"new budget exceeds available parent allocation {ceiling}")
        previous = target.budget_limit
        target.budget_limit = request.amount
        target.version += 1
        row = BudgetAdjustmentRow(
            id=str(uuid4()),
            scope_type=scope_type,
            scope_id=scope_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            previous_limit=previous,
            new_limit=request.amount,
            currency=request.currency,
            approver=request.approver,
            reason=request.reason,
        )
        self.session.add(row)
        self.session.commit()
        return BudgetAdjustmentView.model_validate(row)

    def snapshot_for_action(
        self, action_id: str, *, exclude_action_id: str | None = None
    ) -> dict[str, dict[str, str]]:
        action = self._action(action_id)
        experiment = self.session.get(ExperimentRow, action.experiment_id)
        route = self.session.get(DealRouteRow, action.route_id)
        if experiment is None or route is None:
            raise RuntimeError("action budget parents are missing")
        cell = self.session.get(DealCellRow, route.cell_id)
        if cell is None:
            raise RuntimeError("action Deal Cell is missing")
        return {
            "cell": self._snapshot("cell", cell.id, cell.budget_limit, exclude_action_id),
            "route": self._snapshot("route", route.id, route.budget_limit, exclude_action_id),
            "experiment": self._snapshot(
                "experiment", experiment.id, experiment.budget_limit, exclude_action_id
            ),
        }

    def usage(self, scope_type: str, scope_id: str) -> tuple[Decimal, Decimal]:
        spent = self._sum_scope(BudgetSpendRow, scope_type, scope_id)
        reserved = self._sum_scope(
            BudgetReservationRow,
            scope_type,
            scope_id,
            reservation_status="reserved",
        )
        return spent, reserved

    def _snapshot(
        self,
        scope_type: str,
        scope_id: str,
        limit: Decimal,
        exclude_action_id: str | None,
    ) -> dict[str, str]:
        spent = self._sum_scope(
            BudgetSpendRow, scope_type, scope_id, exclude_action_id=exclude_action_id
        )
        reserved = self._sum_scope(
            BudgetReservationRow,
            scope_type,
            scope_id,
            exclude_action_id=exclude_action_id,
            reservation_status="reserved",
        )
        return {
            "limit": str(limit),
            "spent": str(spent),
            "reserved": str(reserved),
            "remaining": str(limit - spent - reserved),
        }

    def _sum_scope(
        self,
        ledger_model,
        scope_type: str,
        scope_id: str,
        *,
        exclude_action_id: str | None = None,
        reservation_status: str | None = None,
    ) -> Decimal:
        statement = select(func.coalesce(func.sum(ledger_model.amount), 0)).join(
            ActionRow, ActionRow.id == ledger_model.action_id
        )
        if scope_type == "experiment":
            statement = statement.where(ActionRow.experiment_id == scope_id)
        elif scope_type == "route":
            statement = statement.where(ActionRow.route_id == scope_id)
        else:
            statement = statement.join(DealRouteRow, DealRouteRow.id == ActionRow.route_id).where(
                DealRouteRow.cell_id == scope_id
            )
        if exclude_action_id:
            statement = statement.where(ActionRow.id != exclude_action_id)
        if reservation_status:
            statement = statement.where(ledger_model.status == reservation_status)
        return Decimal(self.session.scalar(statement) or 0)

    def _scope_floor(self, scope_type: str, scope_id: str) -> Decimal:
        spent, reserved = self.usage(scope_type, scope_id)
        committed = spent + reserved
        if scope_type == "cell":
            allocated = self.session.scalar(
                select(func.coalesce(func.sum(DealRouteRow.budget_limit), 0)).where(
                    DealRouteRow.cell_id == scope_id,
                    DealRouteRow.lifecycle_status != "merged",
                )
            )
            return max(committed, Decimal(allocated))
        if scope_type == "route":
            allocated = self.session.scalar(
                select(func.coalesce(func.sum(ExperimentRow.budget_limit), 0)).where(
                    ExperimentRow.route_id == scope_id,
                    ExperimentRow.status.not_in(
                        {"succeeded", "failed", "inconclusive", "escalated", "cancelled"}
                    ),
                )
            )
            return max(committed, Decimal(allocated))
        return committed

    def _scope_ceiling(self, scope_type: str, target) -> Decimal | None:
        if scope_type == "cell":
            return None
        if scope_type == "route":
            cell = self.session.get(DealCellRow, target.cell_id)
            if cell is None:
                raise RuntimeError("route Deal Cell is missing")
            other_allocations = Decimal(
                self.session.scalar(
                    select(func.coalesce(func.sum(DealRouteRow.budget_limit), 0)).where(
                        DealRouteRow.cell_id == target.cell_id,
                        DealRouteRow.id != target.id,
                        DealRouteRow.lifecycle_status != "merged",
                    )
                )
                or 0
            )
            return cell.budget_limit - other_allocations
        route = self.session.get(DealRouteRow, target.route_id)
        if route is None:
            raise RuntimeError("experiment route is missing")
        other_allocations = Decimal(
            self.session.scalar(
                select(func.coalesce(func.sum(ExperimentRow.budget_limit), 0)).where(
                    ExperimentRow.route_id == target.route_id,
                    ExperimentRow.id != target.id,
                    ExperimentRow.status.not_in(
                        {"succeeded", "failed", "inconclusive", "escalated", "cancelled"}
                    ),
                )
            )
            or 0
        )
        return route.budget_limit - other_allocations

    def _action(self, action_id: str) -> ActionRow:
        row = self.session.get(ActionRow, action_id)
        if row is None:
            raise LookupError(f"action {action_id} not found")
        return row
