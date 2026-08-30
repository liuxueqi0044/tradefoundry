from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.aggregates import DealCellService, DealRouteService
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.contracts import (
    DealCellCockpit,
    ExperimentView,
    ObservationView,
    RouteCockpit,
    TimelineItem,
)
from tradefoundry.deals.models import (
    ActionAttemptRow,
    ActionRow,
    BudgetAdjustmentRow,
    BudgetDecisionRow,
    BudgetSpendRow,
    DealCellRow,
    DealRouteRow,
    ExperimentOutcomeRow,
    ExperimentRow,
    ObservationRow,
    RouteEvidenceLinkRow,
    RouteLifecycleEventRow,
    StageTransitionRow,
)
from tradefoundry.deals.queue import NextActionService


class DealCockpitService:
    def __init__(self, session: Session):
        self.session = session

    def route(self, route_id: str) -> RouteCockpit:
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        experiments = self.session.scalars(
            select(ExperimentRow)
            .where(ExperimentRow.route_id == route_id)
            .order_by(ExperimentRow.created_at, ExperimentRow.id)
        ).all()
        observations = self._route_observations(route_id)
        next_actions = NextActionService(self.session).evaluate_route(route_id)
        spent, reserved = BudgetService(self.session).usage("route", route_id)
        blockers = sorted({blocker for item in next_actions for blocker in item.blockers})
        if route.lifecycle_status != "active":
            blockers.append(f"route lifecycle is {route.lifecycle_status}")
        return RouteCockpit(
            route=DealRouteService(self.session).get(route_id),
            experiments=[ExperimentView.model_validate(row) for row in experiments],
            observations=[ObservationView.model_validate(row) for row in observations],
            next_actions=next_actions,
            spent=spent,
            reserved=reserved,
            remaining=route.budget_limit - spent - reserved,
            blockers=sorted(set(blockers)),
        )

    def cell(self, cell_id: str, *, timeline_limit: int = 200) -> DealCellCockpit:
        cell = self.session.get(DealCellRow, cell_id)
        if cell is None:
            raise LookupError(f"Deal Cell {cell_id} not found")
        routes = DealRouteService(self.session).list(cell_id)
        route_cockpits = [self.route(route.id) for route in routes]
        spent, reserved = BudgetService(self.session).usage("cell", cell_id)
        return DealCellCockpit(
            cell=DealCellService(self.session).get(cell_id),
            routes=route_cockpits,
            total_spent=spent,
            total_reserved=reserved,
            remaining=cell.budget_limit - spent - reserved,
            timeline=self.timeline(cell_id, limit=timeline_limit),
        )

    def timeline(self, cell_id: str, *, limit: int = 200) -> list[TimelineItem]:
        if limit < 1 or limit > 1000:
            raise ValueError("timeline limit must be between 1 and 1000")
        route_ids = self.session.scalars(
            select(DealRouteRow.id).where(DealRouteRow.cell_id == cell_id)
        ).all()
        if not route_ids:
            if self.session.get(DealCellRow, cell_id) is None:
                raise LookupError(f"Deal Cell {cell_id} not found")
            return []
        items: list[TimelineItem] = []
        transitions = self.session.scalars(
            select(StageTransitionRow).where(StageTransitionRow.route_id.in_(route_ids))
        ).all()
        items.extend(
            TimelineItem(
                at=row.created_at,
                kind="stage_transition",
                item_id=row.id,
                summary=f"{row.from_stage} -> {row.to_stage}: {row.outcome}",
                details={
                    "route_id": row.route_id,
                    "reasons": row.reasons_json,
                    "actor": row.actor,
                },
            )
            for row in transitions
        )
        lifecycle = self.session.scalars(
            select(RouteLifecycleEventRow).where(RouteLifecycleEventRow.route_id.in_(route_ids))
        ).all()
        items.extend(
            TimelineItem(
                at=row.created_at,
                kind="route_lifecycle",
                item_id=row.id,
                summary=f"Route {row.action}: {row.previous_status} -> {row.new_status}",
                details={
                    "route_id": row.route_id,
                    "related_route_id": row.related_route_id,
                    "actor": row.actor,
                },
            )
            for row in lifecycle
        )
        experiments = self.session.scalars(
            select(ExperimentRow).where(ExperimentRow.route_id.in_(route_ids))
        ).all()
        experiment_ids = [row.id for row in experiments]
        items.extend(
            TimelineItem(
                at=row.created_at,
                kind="experiment",
                item_id=row.id,
                summary=f"Experiment {row.experiment_key}: {row.status}",
                details={"route_id": row.route_id, "deadline": row.deadline.isoformat()},
            )
            for row in experiments
        )
        if experiment_ids:
            outcomes = self.session.scalars(
                select(ExperimentOutcomeRow).where(
                    ExperimentOutcomeRow.experiment_id.in_(experiment_ids)
                )
            ).all()
            items.extend(
                TimelineItem(
                    at=row.created_at,
                    kind="experiment_outcome",
                    item_id=row.id,
                    summary=f"Experiment outcome: {row.outcome}",
                    details={
                        "experiment_id": row.experiment_id,
                        "observation_ids": row.observation_ids_json,
                    },
                )
                for row in outcomes
            )
        actions = self.session.scalars(
            select(ActionRow).where(ActionRow.route_id.in_(route_ids))
        ).all()
        action_ids = [row.id for row in actions]
        items.extend(
            TimelineItem(
                at=row.created_at,
                kind="action",
                item_id=row.id,
                summary=f"Action {row.action_key}: {row.status}",
                details={
                    "route_id": row.route_id,
                    "action_type": row.action_type,
                    "estimated_cost": str(row.estimated_cost),
                },
            )
            for row in actions
        )
        if action_ids:
            attempts = self.session.scalars(
                select(ActionAttemptRow).where(ActionAttemptRow.action_id.in_(action_ids))
            ).all()
            items.extend(
                TimelineItem(
                    at=row.started_at,
                    kind="action_attempt",
                    item_id=row.id,
                    summary=f"Action attempt {row.attempt_no}: {row.status}",
                    details={"action_id": row.action_id, "error": row.error_message},
                )
                for row in attempts
            )
            decisions = self.session.scalars(
                select(BudgetDecisionRow).where(BudgetDecisionRow.action_id.in_(action_ids))
            ).all()
            items.extend(
                TimelineItem(
                    at=row.created_at,
                    kind="budget_decision",
                    item_id=row.id,
                    summary=f"Budget decision: {row.decision}",
                    details={
                        "action_id": row.action_id,
                        "requested_amount": str(row.requested_amount),
                        "reasons": row.reasons_json,
                    },
                )
                for row in decisions
            )
            spends = self.session.scalars(
                select(BudgetSpendRow).where(BudgetSpendRow.action_id.in_(action_ids))
            ).all()
            items.extend(
                TimelineItem(
                    at=row.created_at,
                    kind="budget_spend",
                    item_id=row.id,
                    summary=f"Spend recorded: {row.amount} {row.currency}",
                    details={"action_id": row.action_id, "actor": row.actor},
                )
                for row in spends
            )
        observations = self.session.scalars(
            select(ObservationRow).where(ObservationRow.route_id.in_(route_ids))
        ).all()
        items.extend(
            TimelineItem(
                at=row.occurred_at,
                kind="observation",
                item_id=row.id,
                summary=f"Observation: {row.observation_type}",
                details={"route_id": row.route_id, "external_ref": row.external_ref},
            )
            for row in observations
        )
        adjustments = self.session.scalars(
            select(BudgetAdjustmentRow).where(
                (BudgetAdjustmentRow.scope_type == "cell")
                & (BudgetAdjustmentRow.scope_id == cell_id)
                | (
                    (BudgetAdjustmentRow.scope_type == "route")
                    & BudgetAdjustmentRow.scope_id.in_(route_ids)
                )
                | (
                    (BudgetAdjustmentRow.scope_type == "experiment")
                    & BudgetAdjustmentRow.scope_id.in_(experiment_ids)
                )
            )
        ).all()
        items.extend(
            TimelineItem(
                at=row.created_at,
                kind="budget_adjustment",
                item_id=row.id,
                summary=f"Budget adjusted: {row.previous_limit} -> {row.new_limit}",
                details={
                    "scope_type": row.scope_type,
                    "scope_id": row.scope_id,
                    "approver": row.approver,
                },
            )
            for row in adjustments
        )
        return sorted(items, key=lambda item: (item.at, item.item_id), reverse=True)[:limit]

    def _route_observations(self, route_id: str) -> list[ObservationRow]:
        inherited_ids = self.session.scalars(
            select(RouteEvidenceLinkRow.observation_id).where(
                RouteEvidenceLinkRow.route_id == route_id
            )
        ).all()
        rows = self.session.scalars(
            select(ObservationRow)
            .where((ObservationRow.route_id == route_id) | ObservationRow.id.in_(inherited_ids))
            .order_by(ObservationRow.occurred_at, ObservationRow.id)
        ).all()
        return list(rows)
