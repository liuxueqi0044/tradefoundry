from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from tradefoundry.deals.contracts import (
    WorkflowJobCreate,
    WorkflowJobView,
    WorkflowSignalRequest,
)
from tradefoundry.deals.models import WorkflowJobRow, WorkflowSignalRow
from tradefoundry.ingestion.hashing import payload_hash


class WorkflowAdapter(Protocol):
    """Stable port that a future Temporal adapter can implement."""

    def enqueue(self, request: WorkflowJobCreate) -> WorkflowJobView: ...

    def claim_due(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        as_of: datetime | None = None,
    ) -> WorkflowJobView | None: ...

    def complete(self, job_id: str, lease_token: str) -> WorkflowJobView: ...

    def fail(
        self,
        job_id: str,
        lease_token: str,
        error: str,
        *,
        retry_delay_seconds: int = 30,
    ) -> WorkflowJobView: ...

    def wait(self, job_id: str, lease_token: str, reason: str) -> WorkflowJobView: ...

    def signal(self, job_id: str, request: WorkflowSignalRequest) -> WorkflowJobView: ...


class DatabaseWorkflowAdapter:
    """Restart-safe MVP queue with durable leases, retries and signals."""

    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, request: WorkflowJobCreate) -> WorkflowJobView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(WorkflowJobRow).where(WorkflowJobRow.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("workflow key was reused with a different payload")
            return WorkflowJobView.model_validate(existing)
        row = WorkflowJobRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            job_type=request.job_type,
            payload_json=request.payload,
            status="ready",
            attempts=0,
            max_attempts=request.max_attempts,
            available_at=request.available_at,
        )
        self.session.add(row)
        self.session.commit()
        return WorkflowJobView.model_validate(row)

    def claim_due(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        as_of: datetime | None = None,
    ) -> WorkflowJobView | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        now = self._aware(as_of or datetime.now(UTC))
        candidate = self.session.scalar(
            select(WorkflowJobRow)
            .where(
                WorkflowJobRow.attempts < WorkflowJobRow.max_attempts,
                WorkflowJobRow.available_at <= now,
                or_(
                    WorkflowJobRow.status.in_({"ready", "retry"}),
                    (
                        (WorkflowJobRow.status == "running")
                        & (WorkflowJobRow.lease_expires_at <= now)
                    ),
                ),
            )
            .order_by(WorkflowJobRow.available_at, WorkflowJobRow.created_at, WorkflowJobRow.id)
        )
        if candidate is None:
            return None
        lease_token = f"{worker_id}:{uuid4()}"
        previous_status = candidate.status
        statement = (
            update(WorkflowJobRow)
            .where(
                WorkflowJobRow.id == candidate.id,
                WorkflowJobRow.status == previous_status,
                WorkflowJobRow.attempts == candidate.attempts,
            )
            .values(
                status="running",
                attempts=WorkflowJobRow.attempts + 1,
                lease_token=lease_token,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                wait_reason=None,
            )
        )
        result = self.session.execute(statement)
        if result.rowcount != 1:
            self.session.rollback()
            return None
        self.session.commit()
        return self.get(candidate.id)

    def complete(self, job_id: str, lease_token: str) -> WorkflowJobView:
        row = self._leased(job_id, lease_token)
        row.status = "completed"
        row.lease_token = None
        row.lease_expires_at = None
        row.wait_reason = None
        self.session.commit()
        return WorkflowJobView.model_validate(row)

    def fail(
        self,
        job_id: str,
        lease_token: str,
        error: str,
        *,
        retry_delay_seconds: int = 30,
    ) -> WorkflowJobView:
        if retry_delay_seconds < 0 or retry_delay_seconds > 86_400:
            raise ValueError("retry delay must be between 0 and 86400 seconds")
        row = self._leased(job_id, lease_token)
        row.last_error = error
        row.lease_token = None
        row.lease_expires_at = None
        row.wait_reason = None
        if row.attempts >= row.max_attempts:
            row.status = "dead"
        else:
            row.status = "retry"
            row.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        self.session.commit()
        return WorkflowJobView.model_validate(row)

    def wait(self, job_id: str, lease_token: str, reason: str) -> WorkflowJobView:
        if not reason.strip():
            raise ValueError("wait reason is required")
        row = self._leased(job_id, lease_token)
        row.status = "waiting"
        row.wait_reason = reason
        row.lease_token = None
        row.lease_expires_at = None
        self.session.commit()
        return WorkflowJobView.model_validate(row)

    def signal(self, job_id: str, request: WorkflowSignalRequest) -> WorkflowJobView:
        row = self._job(job_id)
        existing = self.session.scalar(
            select(WorkflowSignalRow).where(
                WorkflowSignalRow.job_id == job_id,
                WorkflowSignalRow.signal_key == request.signal_key,
            )
        )
        if existing is not None:
            if existing.payload_json != request.payload:
                raise ValueError("workflow signal key was reused with a different payload")
            return WorkflowJobView.model_validate(row)
        if row.status in {"completed", "dead"}:
            raise ValueError(f"cannot signal a {row.status} workflow")
        self.session.add(
            WorkflowSignalRow(
                id=str(uuid4()),
                job_id=job_id,
                signal_key=request.signal_key,
                payload_json=request.payload,
            )
        )
        if row.status == "waiting":
            row.status = "ready"
            row.wait_reason = None
            row.available_at = datetime.now(UTC)
        self.session.commit()
        return WorkflowJobView.model_validate(row)

    def get(self, job_id: str) -> WorkflowJobView:
        return WorkflowJobView.model_validate(self._job(job_id))

    def list_signals(self, job_id: str) -> list[dict]:
        self._job(job_id)
        rows = self.session.scalars(
            select(WorkflowSignalRow)
            .where(WorkflowSignalRow.job_id == job_id)
            .order_by(WorkflowSignalRow.received_at, WorkflowSignalRow.id)
        ).all()
        return [
            {
                "signal_key": row.signal_key,
                "payload": row.payload_json,
                "received_at": row.received_at,
            }
            for row in rows
        ]

    def _leased(self, job_id: str, lease_token: str) -> WorkflowJobRow:
        row = self._job(job_id)
        if row.status != "running" or row.lease_token != lease_token:
            raise ValueError("workflow lease is missing, stale or owned by another worker")
        expires_at = self._aware(row.lease_expires_at) if row.lease_expires_at else None
        if expires_at is None or expires_at <= datetime.now(UTC):
            raise ValueError("workflow lease has expired")
        return row

    def _job(self, job_id: str) -> WorkflowJobRow:
        row = self.session.get(WorkflowJobRow, job_id)
        if row is None:
            raise LookupError(f"workflow job {job_id} not found")
        return row

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
