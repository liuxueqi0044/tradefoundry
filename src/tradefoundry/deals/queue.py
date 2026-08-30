from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.contracts import ActionQueueItem
from tradefoundry.deals.models import ActionRow, DealRouteRow
from tradefoundry.deals.ports import DenyExternalPolicyPort, PolicyDecisionPort


class NextActionService:
    def __init__(self, session: Session, *, policy_port: PolicyDecisionPort | None = None):
        self.session = session
        self.policy_port = policy_port or DenyExternalPolicyPort()

    def evaluate_route(
        self, route_id: str, *, as_of: datetime | None = None
    ) -> list[ActionQueueItem]:
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        at = as_of or datetime.now(UTC)
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        rows = self.session.scalars(
            select(ActionRow).where(
                ActionRow.route_id == route_id,
                ActionRow.status.in_({"proposed", "blocked", "queued", "failed"}),
            )
        ).all()
        service = ActionService(self.session, policy_port=self.policy_port)
        items = []
        for row in rows:
            blockers = service.blockers(row)
            snapshot = BudgetService(self.session).snapshot_for_action(
                row.id, exclude_action_id=row.id
            )
            if any(
                Decimal(values["remaining"]) < row.estimated_cost for values in snapshot.values()
            ):
                blockers.append("budget guard would deny this action")
            due = row.due_at
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            items.append(
                ActionQueueItem(
                    action=service.get(row.id),
                    executable=not blockers,
                    blockers=blockers,
                    overdue=due < at,
                )
            )
        return sorted(
            items,
            key=lambda item: (
                not item.executable,
                self._aware(item.action.due_at),
                item.action.id,
            ),
        )

    def executable_for_cell(
        self, cell_id: str, *, as_of: datetime | None = None
    ) -> list[ActionQueueItem]:
        route_ids = self.session.scalars(
            select(DealRouteRow.id).where(DealRouteRow.cell_id == cell_id)
        ).all()
        items = [
            item
            for route_id in route_ids
            for item in self.evaluate_route(route_id, as_of=as_of)
            if item.executable
        ]
        return sorted(items, key=lambda item: (self._aware(item.action.due_at), item.action.id))

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
