from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tradefoundry.ingestion.contracts import (
    FetchRunCreate,
    SourceVersionCreate,
    TimeWindow,
)
from tradefoundry.ingestion.models import DataQualityAlertRow, QualityAssessmentRow
from tradefoundry.ingestion.registry import SourceRegistry
from tradefoundry.ingestion.runs import FetchRunService, IngestionOrchestrator


def test_empty_feed_is_flagged_and_failure_does_not_affect_other_source(
    session, source_factory, artifact_store
):
    empty = source_factory(
        key="empty-source",
        config={"pages": [[]]},
        quality={"minimum_records": 1},
    )
    healthy = source_factory(key="healthy-source")
    now = datetime.now(UTC)
    for source in (empty, healthy):
        run = FetchRunService(session).create(
            FetchRunCreate(
                source_id=source.id,
                window=TimeWindow(start=now - timedelta(days=1), end=now),
            )
        )
        result = IngestionOrchestrator(session, artifact_store).execute(run.id)
        assert result.status.value == "succeeded"
    assessments = session.scalars(
        select(QualityAssessmentRow).order_by(QualityAssessmentRow.source_id)
    ).all()
    by_source = {item.source_id: item for item in assessments}
    assert "empty_or_below_minimum" in by_source[empty.id].anomalies
    assert by_source[healthy.id].status == "healthy"


def test_duplicate_surge_is_detected_on_explicit_rerun(session, source_factory, artifact_store):
    source = source_factory(
        key="duplicate-source",
        config={"pages": [[{"id": "1"}, {"id": "2"}]]},
        quality={"maximum_duplicate_ratio": 0.2},
    )
    now = datetime.now(UTC)
    service = FetchRunService(session)
    original = service.create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(days=1), end=now),
        )
    )
    IngestionOrchestrator(session, artifact_store).execute(original.id)
    rerun = service.rerun(original.id)
    IngestionOrchestrator(session, artifact_store).execute(rerun.id)
    assessment = session.scalar(
        select(QualityAssessmentRow).where(QualityAssessmentRow.fetch_run_id == rerun.id)
    )
    assert "duplicate_surge" in assessment.anomalies


def test_field_presence_drop_creates_persistent_alert(session, source_factory, artifact_store):
    source = source_factory(
        key="field-drop-source",
        config={"pages": [[{"id": "1", "spec": "A"}, {"id": "2", "spec": "B"}]]},
        quality={"maximum_field_drop_ratio": 0.5},
    )
    now = datetime.now(UTC)
    first = FetchRunService(session).create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(days=2), end=now - timedelta(days=1)),
        )
    )
    IngestionOrchestrator(session, artifact_store).execute(first.id)

    registry = SourceRegistry(session)
    registry.add_version(
        source.id,
        SourceVersionCreate(connector_config={"pages": [[{"id": "3"}, {"id": "4"}]]}),
    )
    registry.activate(source.id)
    second = FetchRunService(session).create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(days=1), end=now),
        )
    )
    IngestionOrchestrator(session, artifact_store).execute(second.id)
    assessment = session.scalar(
        select(QualityAssessmentRow).where(QualityAssessmentRow.fetch_run_id == second.id)
    )
    alert = session.scalar(
        select(DataQualityAlertRow).where(
            DataQualityAlertRow.fetch_run_id == second.id,
            DataQualityAlertRow.anomaly_code == "field_presence_drop",
        )
    )
    assert "field_presence_drop" in assessment.anomalies
    assert assessment.metrics["dropped_fields"] == ["spec"]
    assert alert is not None
