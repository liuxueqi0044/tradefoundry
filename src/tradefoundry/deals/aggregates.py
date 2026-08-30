from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.contracts import (
    DealCellCreate,
    DealCellUpdate,
    DealCellView,
    DealRouteCreate,
    DealRouteView,
)
from tradefoundry.deals.models import DealCellRow, DealRouteRow, StageTransitionRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.opportunity.compiler import OpportunityCompiler
from tradefoundry.opportunity.issuance import DealCellIssuanceService
from tradefoundry.opportunity.models import RouteCandidateRow


class OptimisticLockError(ValueError):
    pass


class DealCellService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: DealCellCreate) -> DealCellView:
        if request.amount <= 0:
            raise ValueError("Deal Cell budget must be greater than zero")
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(DealCellRow).where(
                DealCellRow.issuance_command_id == request.issuance_command_id
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("issuance command was reused with different Deal Cell inputs")
            return DealCellView.model_validate(existing)
        issuance = DealCellIssuanceService(self.session).get(request.issuance_command_id)
        if issuance.command_status != "ready" or not issuance.deal_cell_key:
            raise ValueError("only a ready Deal Cell issuance command can create a Cell")
        hypothesis = OpportunityCompiler(self.session).get(issuance.hypothesis_id)
        row = DealCellRow(
            id=str(uuid4()),
            cell_key=issuance.deal_cell_key,
            issuance_command_id=issuance.id,
            request_hash=request_hash,
            hypothesis_id=issuance.hypothesis_id,
            owner=request.owner,
            status="active",
            version=1,
            budget_limit=request.amount,
            currency=request.currency,
            boundaries_json={
                "unknowns": hypothesis.unknowns_json,
                "risks": hypothesis.risks_json,
                "stop_conditions": hypothesis.stop_conditions_json,
            },
            command_snapshot_json=issuance.payload_json,
        )
        self.session.add(row)
        self.session.commit()
        return DealCellView.model_validate(row)

    def update_owner(self, cell_id: str, request: DealCellUpdate) -> DealCellView:
        result = self.session.execute(
            update(DealCellRow)
            .where(DealCellRow.id == cell_id, DealCellRow.version == request.expected_version)
            .values(owner=request.owner, version=DealCellRow.version + 1)
        )
        if result.rowcount != 1:
            self.session.rollback()
            if self.session.get(DealCellRow, cell_id) is None:
                raise LookupError(f"Deal Cell {cell_id} not found")
            raise OptimisticLockError("Deal Cell version conflict")
        self.session.commit()
        return self.get(cell_id)

    def get(self, cell_id: str) -> DealCellView:
        row = self.session.get(DealCellRow, cell_id)
        if row is None:
            raise LookupError(f"Deal Cell {cell_id} not found")
        return DealCellView.model_validate(row)


class DealRouteService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, cell_id: str, request: DealRouteCreate) -> DealRouteView:
        cell = self.session.get(DealCellRow, cell_id)
        if cell is None:
            raise LookupError(f"Deal Cell {cell_id} not found")
        if cell.status != "active":
            raise ValueError("routes can only be added to an active Deal Cell")
        if request.currency != cell.currency:
            raise ValueError("route and Deal Cell currencies must match")
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(DealRouteRow).where(
                DealRouteRow.cell_id == cell_id,
                DealRouteRow.route_key == request.route_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("route key was reused with a different payload")
            return DealRouteView.model_validate(existing)
        candidate = self.session.get(RouteCandidateRow, request.source_route_candidate_id)
        if candidate is None:
            raise LookupError(f"route candidate {request.source_route_candidate_id} not found")
        allowed_ids = set(cell.command_snapshot_json.get("route_candidate_ids", []))
        if candidate.id not in allowed_ids:
            raise ValueError("route candidate is outside the issued hypothesis")
        if candidate.feasibility != "feasible":
            raise ValueError("an excluded route candidate cannot create a Deal Route")
        allocated = self.session.scalar(
            select(func.coalesce(func.sum(DealRouteRow.budget_limit), 0)).where(
                DealRouteRow.cell_id == cell_id,
                DealRouteRow.lifecycle_status != "merged",
            )
        )
        if Decimal(allocated) + request.amount > cell.budget_limit:
            raise ValueError("route budgets exceed the Deal Cell budget")
        row = DealRouteRow(
            id=str(uuid4()),
            cell_id=cell_id,
            route_key=request.route_key,
            source_route_candidate_id=candidate.id,
            request_hash=request_hash,
            route_type=candidate.route_type,
            roles_json={
                **request.roles,
                "participant_candidate_ids": candidate.participant_candidate_ids_json,
            },
            stage="hypothesized",
            lifecycle_status="active",
            version=1,
            budget_limit=request.amount,
            currency=request.currency,
        )
        self.session.add(row)
        self.session.flush()
        self.session.add(
            StageTransitionRow(
                id=str(uuid4()),
                route_id=row.id,
                idempotency_key=f"route-genesis:{row.id}",
                request_hash=payload_hash({"route_id": row.id, "stage": "hypothesized"}),
                from_stage="issued",
                to_stage="hypothesized",
                expected_version=0,
                outcome="accepted",
                reasons_json=[],
                evidence_snapshot_json={
                    "hypothesis_id": cell.hypothesis_id,
                    "source_route_candidate_id": candidate.id,
                },
                actor="system",
                reason="Created from a passing, versioned issuance command.",
            )
        )
        self.session.commit()
        return DealRouteView.model_validate(row)

    def get(self, route_id: str) -> DealRouteView:
        row = self.session.get(DealRouteRow, route_id)
        if row is None:
            raise LookupError(f"Deal Route {route_id} not found")
        return DealRouteView.model_validate(row)

    def list(self, cell_id: str) -> list[DealRouteView]:
        if self.session.get(DealCellRow, cell_id) is None:
            raise LookupError(f"Deal Cell {cell_id} not found")
        rows = self.session.scalars(
            select(DealRouteRow)
            .where(DealRouteRow.cell_id == cell_id)
            .order_by(DealRouteRow.created_at, DealRouteRow.id)
        ).all()
        return [DealRouteView.model_validate(row) for row in rows]
