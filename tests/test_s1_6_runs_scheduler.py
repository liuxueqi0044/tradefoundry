from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.contracts import (
    ArtifactCandidate,
    ConnectorBatch,
    FetchRunCreate,
    RunStatus,
    SourceRecordCandidate,
    TimeWindow,
)
from tradefoundry.ingestion.models import DataQualityAlertRow, SourceRecordRow
from tradefoundry.ingestion.runs import (
    FetchRunService,
    IngestionOrchestrator,
    InvalidRunTransition,
)
from tradefoundry.ingestion.scheduler import SchedulerService
from tradefoundry.ingestion.worker import run_worker_once


def test_same_source_window_is_idempotent_and_explicit_rerun_gets_new_attempt(
    session, source_factory
):
    source = source_factory()
    now = datetime.now(UTC)
    request = FetchRunCreate(
        source_id=source.id,
        window=TimeWindow(start=now - timedelta(days=1), end=now),
    )
    service = FetchRunService(session)
    first = service.create(request)
    duplicate = service.create(request)
    retry = service.rerun(first.id)
    assert duplicate.id == first.id
    assert retry.id != first.id
    assert retry.attempt == 2
    assert retry.parent_run_id == first.id


def test_pause_resume_cancel_state_transitions(session, source_factory):
    source = source_factory()
    now = datetime.now(UTC)
    run = FetchRunService(session).create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(hours=1), end=now),
        )
    )
    service = FetchRunService(session)
    assert service.pause(run.id).status == RunStatus.PAUSED
    assert service.resume(run.id).status == RunStatus.QUEUED
    assert service.cancel(run.id).status == RunStatus.CANCELLED
    with pytest.raises(InvalidRunTransition):
        service.resume(run.id)


def test_scheduler_enqueues_each_due_window_once(session, source_factory):
    source_factory()
    now = datetime.now(UTC)
    first = SchedulerService(session).enqueue_due(now)
    second = SchedulerService(session).enqueue_due(now)
    assert len(first) == 1
    assert second == []


class InterruptOnceConnector(BaseConnector):
    name = "interrupt-once"
    version = "test-1"

    def __init__(self):
        self.should_fail = True

    def fetch(self, context):
        start = int((context.cursor or {}).get("page", 0))
        for page in range(start, 2):
            yield ConnectorBatch(
                artifacts=[
                    ArtifactCandidate(
                        content=f"page-{page}".encode(), media_type="application/json"
                    )
                ],
                records=[
                    SourceRecordCandidate(
                        external_id=str(page), payload={"id": str(page)}, artifact_index=0
                    )
                ],
                next_cursor={"page": page + 1},
            )
            if page == 0 and self.should_fail:
                self.should_fail = False
                raise RuntimeError("simulated connection loss")


def test_failed_run_resumes_from_checkpoint_and_other_source_still_runs(
    session, source_factory, artifact_store
):
    interrupted_source = source_factory(
        key="interrupted-source", quality={"maximum_consecutive_failures": 1}
    )
    healthy_source = source_factory(key="isolated-healthy-source")
    now = datetime.now(UTC)
    window = TimeWindow(start=now - timedelta(days=1), end=now)
    service = FetchRunService(session)
    interrupted = service.create(FetchRunCreate(source_id=interrupted_source.id, window=window))
    connector = InterruptOnceConnector()
    failed = IngestionOrchestrator(session, artifact_store).execute(interrupted.id, connector)
    assert failed.status == RunStatus.FAILED
    assert failed.cursor_after == {"page": 1}
    alert = session.scalar(
        select(DataQualityAlertRow).where(
            DataQualityAlertRow.fetch_run_id == failed.id,
            DataQualityAlertRow.anomaly_code == "repeated_failures",
        )
    )
    assert alert is not None

    healthy = service.create(FetchRunCreate(source_id=healthy_source.id, window=window))
    healthy_result = IngestionOrchestrator(session, artifact_store).execute(healthy.id)
    assert healthy_result.status == RunStatus.SUCCEEDED

    retry = service.retry(failed.id)
    assert retry.cursor_before == {"page": 1}
    completed = IngestionOrchestrator(session, artifact_store).execute(retry.id, connector)
    assert completed.status == RunStatus.SUCCEEDED
    count = session.scalar(
        select(func.count())
        .select_from(SourceRecordRow)
        .where(SourceRecordRow.source_id == interrupted_source.id)
    )
    assert count == 2


def test_worker_enqueues_and_executes_due_sources(session, source_factory, artifact_store):
    source_factory(key="worker-source-a")
    source_factory(key="worker-source-b")
    results = run_worker_once(session, artifact_store, now=datetime.now(UTC))
    assert len(results) == 2
    assert {result.status for result in results} == {RunStatus.SUCCEEDED}
