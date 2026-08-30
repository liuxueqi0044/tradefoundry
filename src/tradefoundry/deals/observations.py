from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.contracts import ObservationCreate, ObservationView
from tradefoundry.deals.models import ActionRow, DealRouteRow, ExperimentRow, ObservationRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.evidence import require_reliable_claim


class ObservationService:
    def __init__(self, session: Session):
        self.session = session

    def record(self, route_id: str, request: ObservationCreate) -> ObservationView:
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        request_hash = payload_hash({"route_id": route_id, **request.model_dump(mode="json")})
        existing = self.session.scalar(
            select(ObservationRow).where(ObservationRow.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("observation idempotency key was reused with a different payload")
            return ObservationView.model_validate(existing)
        if request.experiment_id is not None:
            experiment = self.session.get(ExperimentRow, request.experiment_id)
            if experiment is None or experiment.route_id != route_id:
                raise ValueError("observation experiment does not belong to the route")
        if request.action_id is not None:
            action = self.session.get(ActionRow, request.action_id)
            if action is None or action.route_id != route_id:
                raise ValueError("observation action does not belong to the route")
            if request.experiment_id and action.experiment_id != request.experiment_id:
                raise ValueError("observation action and experiment are inconsistent")
        if request.evidence_claim_id is not None:
            require_reliable_claim(self.session, request.evidence_claim_id)
        row = ObservationRow(
            id=str(uuid4()),
            route_id=route_id,
            experiment_id=request.experiment_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            observation_type=request.observation_type,
            raw_text=request.raw_text,
            structured_interpretation_json=request.structured_interpretation,
            evidence_claim_id=request.evidence_claim_id,
            external_ref=request.external_ref,
            occurred_at=request.occurred_at,
            impact_proposal_json=request.impact_proposal,
        )
        self.session.add(row)
        self.session.commit()
        return ObservationView.model_validate(row)

    def list(self, route_id: str) -> list[ObservationView]:
        rows = self.session.scalars(
            select(ObservationRow)
            .where(ObservationRow.route_id == route_id)
            .order_by(ObservationRow.occurred_at, ObservationRow.id)
        ).all()
        return [ObservationView.model_validate(row) for row in rows]
