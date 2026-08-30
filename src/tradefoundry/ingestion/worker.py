from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.contracts import FetchRunView, RunStatus
from tradefoundry.ingestion.models import FetchRunRow
from tradefoundry.ingestion.runs import IngestionOrchestrator
from tradefoundry.ingestion.scheduler import SchedulerService


def run_worker_once(
    session: Session,
    artifact_store: FileSystemArtifactStore,
    *,
    now: datetime | None = None,
) -> list[FetchRunView]:
    SchedulerService(session).enqueue_due(now)
    queued = session.scalars(
        select(FetchRunRow)
        .where(FetchRunRow.status == RunStatus.QUEUED.value)
        .order_by(FetchRunRow.priority, FetchRunRow.requested_at)
    ).all()
    orchestrator = IngestionOrchestrator(session, artifact_store)
    return [orchestrator.execute(run.id) for run in queued]
