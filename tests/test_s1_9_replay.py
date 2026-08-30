from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from tradefoundry.ingestion.contracts import FetchRunCreate, ReplayRequest, TimeWindow
from tradefoundry.ingestion.models import ArtifactBlobRow, SourceRecordRow
from tradefoundry.ingestion.replay import ReplayService
from tradefoundry.ingestion.runs import FetchRunService, IngestionOrchestrator


def test_replay_is_reproducible_and_does_not_overwrite_history(
    session, source_factory, artifact_store
):
    source = source_factory(
        key="replay-source",
        config={"pages": [[{"id": "1", "value": "a"}], [{"id": "2", "value": "b"}]]},
    )
    now = datetime.now(UTC)
    window = TimeWindow(start=now - timedelta(days=1), end=now)
    run = FetchRunService(session).create(FetchRunCreate(source_id=source.id, window=window))
    IngestionOrchestrator(session, artifact_store).execute(run.id)
    records_before = session.scalar(select(func.count()).select_from(SourceRecordRow))
    artifacts_before = session.scalar(select(func.count()).select_from(ArtifactBlobRow))

    report = ReplayService(session, artifact_store).replay(
        ReplayRequest(source_id=source.id, window=window)
    )

    assert report.added_hashes == []
    assert report.missing_hashes == []
    assert len(report.unchanged_hashes) == 2
    assert session.scalar(select(func.count()).select_from(SourceRecordRow)) == records_before
    assert session.scalar(select(func.count()).select_from(ArtifactBlobRow)) == artifacts_before
