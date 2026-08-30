from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.aggregates import OptimisticLockError
from tradefoundry.deals.contracts import (
    DealRouteView,
    RouteForkRequest,
    RouteLifecycleRequest,
    RouteMergeRequest,
)
from tradefoundry.deals.models import (
    DealCellRow,
    DealRouteRow,
    ObservationRow,
    RouteEvidenceLinkRow,
    RouteLifecycleEventRow,
    StageTransitionRow,
)
from tradefoundry.ingestion.hashing import payload_hash


class RouteLifecycleService:
    """Changes route lifecycle without rewriting its evidence or stage history."""

    def __init__(self, session: Session):
        self.session = session

    def pause(self, route_id: str, request: RouteLifecycleRequest) -> DealRouteView:
        return self._change(route_id, request, action="pause", allowed={"active"}, target="paused")

    def resume(self, route_id: str, request: RouteLifecycleRequest) -> DealRouteView:
        return self._change(route_id, request, action="resume", allowed={"paused"}, target="active")

    def terminate(self, route_id: str, request: RouteLifecycleRequest) -> DealRouteView:
        return self._change(
            route_id,
            request,
            action="terminate",
            allowed={"active", "paused"},
            target="terminated",
        )

    def fork(self, route_id: str, request: RouteForkRequest) -> DealRouteView:
        parent = self._route(route_id)
        request_hash = self._request_hash("fork", route_id, request)
        existing = self._existing(request.idempotency_key, request_hash)
        if existing is not None:
            if existing.related_route_id is None:
                raise RuntimeError("fork event has no child route")
            return DealRouteView.model_validate(self._route(existing.related_route_id))
        self._require_version(parent, request.expected_version)
        if parent.lifecycle_status not in {"active", "paused"}:
            raise ValueError(f"route cannot be forked from {parent.lifecycle_status}")
        if request.currency != parent.currency:
            raise ValueError("fork and parent route currencies must match")
        if request.amount <= 0:
            raise ValueError("fork budget must be greater than zero")
        duplicate = self.session.scalar(
            select(DealRouteRow).where(
                DealRouteRow.cell_id == parent.cell_id,
                DealRouteRow.route_key == request.route_key,
            )
        )
        if duplicate is not None:
            raise ValueError("route key already exists in this Deal Cell")
        self._ensure_cell_allocation(parent.cell_id, request.amount)
        self._atomic_route_update(
            parent,
            request.expected_version,
            lifecycle_status=parent.lifecycle_status,
        )
        child = DealRouteRow(
            id=str(uuid4()),
            cell_id=parent.cell_id,
            route_key=request.route_key,
            source_route_candidate_id=parent.source_route_candidate_id,
            request_hash=request_hash,
            route_type=parent.route_type,
            roles_json=dict(parent.roles_json),
            stage=parent.stage,
            lifecycle_status="active",
            version=1,
            budget_limit=request.amount,
            currency=request.currency,
            parent_route_id=parent.id,
        )
        self.session.add(child)
        self.session.flush()
        inherited_observation_ids = self._evidence_ids(parent.id)
        for observation_id in inherited_observation_ids:
            self.session.add(
                RouteEvidenceLinkRow(
                    id=str(uuid4()),
                    route_id=child.id,
                    observation_id=observation_id,
                    inherited_from_route_id=parent.id,
                )
            )
        self.session.add(
            StageTransitionRow(
                id=str(uuid4()),
                route_id=child.id,
                idempotency_key=f"route-fork-genesis:{child.id}",
                request_hash=payload_hash(
                    {"route_id": child.id, "parent_route_id": parent.id, "stage": child.stage}
                ),
                from_stage=f"fork:{parent.id}",
                to_stage=child.stage,
                expected_version=0,
                outcome="accepted",
                reasons_json=[],
                evidence_snapshot_json={
                    "parent_route_id": parent.id,
                    "inherited_observation_ids": inherited_observation_ids,
                },
                actor=request.actor,
                reason=request.reason,
            )
        )
        self._event(
            parent,
            request,
            request_hash=request_hash,
            action="fork",
            previous=parent.lifecycle_status,
            target=parent.lifecycle_status,
            related_route_id=child.id,
        )
        self.session.commit()
        return DealRouteView.model_validate(child)

    def merge(self, target_route_id: str, request: RouteMergeRequest) -> DealRouteView:
        target = self._route(target_route_id)
        source = self._route(request.source_route_id)
        request_hash = self._request_hash("merge", target_route_id, request)
        existing = self._existing(request.idempotency_key, request_hash)
        if existing is not None:
            if existing.related_route_id is None:
                raise RuntimeError("merge event has no target route")
            return DealRouteView.model_validate(self._route(existing.related_route_id))
        if source.id == target.id:
            raise ValueError("a route cannot merge into itself")
        if source.cell_id != target.cell_id:
            raise ValueError("routes from different Deal Cells cannot be merged")
        self._require_version(target, request.target_expected_version)
        self._require_version(source, request.source_expected_version)
        if target.lifecycle_status != "active":
            raise ValueError("merge target must be active")
        if source.lifecycle_status not in {"active", "paused"}:
            raise ValueError(f"route cannot be merged from {source.lifecycle_status}")
        existing_target_evidence = set(self._evidence_ids(target.id))
        for observation_id in self._evidence_ids(source.id):
            if observation_id not in existing_target_evidence:
                self.session.add(
                    RouteEvidenceLinkRow(
                        id=str(uuid4()),
                        route_id=target.id,
                        observation_id=observation_id,
                        inherited_from_route_id=source.id,
                    )
                )
        previous = source.lifecycle_status
        self._atomic_route_update(
            source,
            request.source_expected_version,
            lifecycle_status="merged",
            merged_into_route_id=target.id,
        )
        self._atomic_route_update(
            target,
            request.target_expected_version,
            lifecycle_status=target.lifecycle_status,
        )
        self._event(
            source,
            request,
            request_hash=request_hash,
            action="merge",
            previous=previous,
            target="merged",
            related_route_id=target.id,
        )
        self.session.commit()
        return DealRouteView.model_validate(target)

    def _change(
        self,
        route_id: str,
        request: RouteLifecycleRequest,
        *,
        action: str,
        allowed: set[str],
        target: str,
    ) -> DealRouteView:
        route = self._route(route_id)
        request_hash = self._request_hash(action, route_id, request)
        existing = self._existing(request.idempotency_key, request_hash)
        if existing is not None:
            return DealRouteView.model_validate(route)
        self._require_version(route, request.expected_version)
        if route.lifecycle_status not in allowed:
            raise ValueError(f"route cannot {action} from {route.lifecycle_status}")
        previous = route.lifecycle_status
        self._atomic_route_update(
            route,
            request.expected_version,
            lifecycle_status=target,
        )
        self._event(
            route,
            request,
            request_hash=request_hash,
            action=action,
            previous=previous,
            target=target,
        )
        self.session.commit()
        return DealRouteView.model_validate(route)

    def _event(
        self,
        route: DealRouteRow,
        request: RouteLifecycleRequest | RouteForkRequest | RouteMergeRequest,
        *,
        request_hash: str,
        action: str,
        previous: str,
        target: str,
        related_route_id: str | None = None,
    ) -> None:
        self.session.add(
            RouteLifecycleEventRow(
                id=str(uuid4()),
                route_id=route.id,
                idempotency_key=request.idempotency_key,
                request_hash=request_hash,
                action=action,
                previous_status=previous,
                new_status=target,
                related_route_id=related_route_id,
                actor=request.actor,
                reason=request.reason,
            )
        )

    def _existing(self, key: str, request_hash: str) -> RouteLifecycleEventRow | None:
        row = self.session.scalar(
            select(RouteLifecycleEventRow).where(RouteLifecycleEventRow.idempotency_key == key)
        )
        if row is not None and row.request_hash != request_hash:
            raise ValueError("lifecycle idempotency key was reused with a different payload")
        return row

    def _evidence_ids(self, route_id: str) -> list[str]:
        direct = self.session.scalars(
            select(ObservationRow.id).where(ObservationRow.route_id == route_id)
        ).all()
        inherited = self.session.scalars(
            select(RouteEvidenceLinkRow.observation_id).where(
                RouteEvidenceLinkRow.route_id == route_id
            )
        ).all()
        return sorted(set(direct) | set(inherited))

    def _ensure_cell_allocation(self, cell_id: str, increment: Decimal) -> None:
        cell = self.session.get(DealCellRow, cell_id)
        if cell is None:
            raise RuntimeError("route Deal Cell is missing")
        allocated = Decimal(
            self.session.scalar(
                select(func.coalesce(func.sum(DealRouteRow.budget_limit), 0)).where(
                    DealRouteRow.cell_id == cell_id,
                    DealRouteRow.lifecycle_status != "merged",
                )
            )
            or 0
        )
        if allocated + increment > cell.budget_limit:
            raise ValueError("fork budget would exceed the Deal Cell budget")

    @staticmethod
    def _require_version(route: DealRouteRow, expected: int) -> None:
        if route.version != expected:
            raise OptimisticLockError(
                f"route version conflict: expected {expected}, actual {route.version}"
            )

    def _atomic_route_update(
        self,
        route: DealRouteRow,
        expected_version: int,
        *,
        lifecycle_status: str,
        merged_into_route_id: str | None = None,
    ) -> None:
        values = {
            "lifecycle_status": lifecycle_status,
            "version": DealRouteRow.version + 1,
        }
        if merged_into_route_id is not None:
            values["merged_into_route_id"] = merged_into_route_id
        result = self.session.execute(
            update(DealRouteRow)
            .where(
                DealRouteRow.id == route.id,
                DealRouteRow.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise OptimisticLockError("route changed concurrently before lifecycle commit")

    @staticmethod
    def _request_hash(action: str, route_id: str, request: object) -> str:
        return payload_hash(
            {
                "action": action,
                "route_id": route_id,
                **request.model_dump(mode="json"),  # type: ignore[attr-defined]
            }
        )

    def _route(self, route_id: str) -> DealRouteRow:
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        return route
