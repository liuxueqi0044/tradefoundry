from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.aggregates import OptimisticLockError
from tradefoundry.deals.contracts import (
    ExperimentClose,
    ExperimentCreate,
    ExperimentOutcomeView,
    ExperimentView,
)
from tradefoundry.deals.models import (
    DealRouteRow,
    ExperimentOutcomeRow,
    ExperimentRow,
    ObservationRow,
)
from tradefoundry.ingestion.hashing import payload_hash

TERMINAL_EXPERIMENT_STATUSES = {
    "succeeded",
    "failed",
    "inconclusive",
    "escalated",
    "cancelled",
}


class ExperimentService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, route_id: str, request: ExperimentCreate) -> ExperimentView:
        route = self.session.get(DealRouteRow, route_id)
        if route is None:
            raise LookupError(f"Deal Route {route_id} not found")
        if route.lifecycle_status != "active":
            raise ValueError("experiments require an active route")
        if request.currency != route.currency:
            raise ValueError("experiment and route currencies must match")
        if request.amount <= 0:
            raise ValueError("experiment budget must be greater than zero")
        if not all(
            (
                request.success_condition,
                request.failure_condition,
                request.inconclusive_condition,
            )
        ):
            raise ValueError("all experiment outcome conditions are required")
        request_hash = payload_hash({"route_id": route_id, **request.model_dump(mode="json")})
        existing = self.session.scalar(
            select(ExperimentRow).where(ExperimentRow.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("experiment idempotency key was reused with a different payload")
            return ExperimentView.model_validate(existing)
        allocated = self.session.scalar(
            select(func.coalesce(func.sum(ExperimentRow.budget_limit), 0)).where(
                ExperimentRow.route_id == route_id,
                ExperimentRow.status.not_in(TERMINAL_EXPERIMENT_STATUSES),
            )
        )
        if Decimal(allocated) + request.amount > route.budget_limit:
            raise ValueError("active experiment budgets exceed the route budget")
        row = ExperimentRow(
            id=str(uuid4()),
            route_id=route_id,
            experiment_key=request.experiment_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            question=request.question,
            hypothesis=request.hypothesis,
            metric_name=request.metric_name,
            budget_limit=request.amount,
            currency=request.currency,
            deadline=request.deadline,
            on_expiry=request.on_expiry,
            status="planned",
            success_condition_json=request.success_condition,
            failure_condition_json=request.failure_condition,
            inconclusive_condition_json=request.inconclusive_condition,
            version=1,
        )
        self.session.add(row)
        self.session.commit()
        return ExperimentView.model_validate(row)

    def start(self, experiment_id: str, *, expected_version: int) -> ExperimentView:
        result = self.session.execute(
            update(ExperimentRow)
            .where(
                ExperimentRow.id == experiment_id,
                ExperimentRow.version == expected_version,
                ExperimentRow.status == "planned",
            )
            .values(status="running", version=ExperimentRow.version + 1)
        )
        if result.rowcount != 1:
            self.session.rollback()
            row = self.session.get(ExperimentRow, experiment_id)
            if row is None:
                raise LookupError(f"experiment {experiment_id} not found")
            raise OptimisticLockError("experiment is not planned or version conflicts")
        self.session.commit()
        return self.get(experiment_id)

    def close(self, experiment_id: str, request: ExperimentClose) -> ExperimentOutcomeView:
        request_hash = payload_hash(
            {"experiment_id": experiment_id, **request.model_dump(mode="json")}
        )
        existing = self.session.scalar(
            select(ExperimentOutcomeRow).where(
                ExperimentOutcomeRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("experiment close key was reused with a different payload")
            return ExperimentOutcomeView.model_validate(existing)
        experiment = self.session.get(ExperimentRow, experiment_id)
        if experiment is None:
            raise LookupError(f"experiment {experiment_id} not found")
        if experiment.version != request.expected_version:
            raise OptimisticLockError("experiment version conflict")
        if experiment.status in TERMINAL_EXPERIMENT_STATUSES:
            raise ValueError(f"experiment already ended as {experiment.status}")
        observations = [
            self.session.get(ObservationRow, observation_id)
            for observation_id in request.observation_ids
        ]
        if any(
            observation is None or observation.route_id != experiment.route_id
            for observation in observations
        ):
            raise ValueError("experiment outcome cites an invalid route observation")
        result = self.session.execute(
            update(ExperimentRow)
            .where(
                ExperimentRow.id == experiment_id,
                ExperimentRow.version == request.expected_version,
                ExperimentRow.status.not_in(TERMINAL_EXPERIMENT_STATUSES),
            )
            .values(status=request.outcome, version=ExperimentRow.version + 1)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise OptimisticLockError("experiment changed concurrently before close")
        row = ExperimentOutcomeRow(
            id=str(uuid4()),
            experiment_id=experiment_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            outcome=request.outcome,
            observation_ids_json=sorted(set(request.observation_ids)),
            actor=request.actor,
            reason=request.reason,
        )
        self.session.add(row)
        self.session.commit()
        return ExperimentOutcomeView.model_validate(row)

    def close_due(self, *, as_of: datetime | None = None) -> list[ExperimentOutcomeView]:
        at = as_of or datetime.now(UTC)
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        rows = self.session.scalars(
            select(ExperimentRow).where(
                ExperimentRow.status.in_({"planned", "running"}),
                ExperimentRow.deadline <= at,
            )
        ).all()
        results = []
        for row in rows:
            outcome = "inconclusive" if row.on_expiry == "close_inconclusive" else "escalated"
            results.append(
                self.close(
                    row.id,
                    ExperimentClose(
                        idempotency_key=f"experiment-expiry:{row.id}:{row.deadline.isoformat()}",
                        expected_version=row.version,
                        outcome=outcome,
                        actor="system",
                        reason="Experiment deadline elapsed without a terminal outcome.",
                    ),
                )
            )
        return results

    def get(self, experiment_id: str) -> ExperimentView:
        row = self.session.get(ExperimentRow, experiment_id)
        if row is None:
            raise LookupError(f"experiment {experiment_id} not found")
        return ExperimentView.model_validate(row)

    def list(self, route_id: str) -> list[ExperimentView]:
        rows = self.session.scalars(
            select(ExperimentRow)
            .where(ExperimentRow.route_id == route_id)
            .order_by(ExperimentRow.deadline, ExperimentRow.id)
        ).all()
        return [ExperimentView.model_validate(row) for row in rows]
