from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.contracts import (
    ArtifactCandidate,
    ConnectorBatch,
    ConnectorContext,
    FetchRunCreate,
    SourceRecordCandidate,
    TimeWindow,
)
from tradefoundry.ingestion.models import ChangeEventRow
from tradefoundry.ingestion.runs import FetchRunService, IngestionOrchestrator


class OneRecordConnector(BaseConnector):
    name = "one-record"
    version = "test-1"

    def __init__(self, candidate: SourceRecordCandidate):
        self.candidate = candidate

    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        yield ConnectorBatch(
            artifacts=[
                ArtifactCandidate(
                    content=str(self.candidate.payload).encode(), media_type="application/json"
                )
            ],
            records=[self.candidate.model_copy(update={"artifact_index": 0})],
            next_cursor={"done": True},
        )


def test_added_updated_revoked_deadline_and_attachment_changes_are_recorded(
    session, source_factory, artifact_store
):
    source = source_factory()
    now = datetime.now(UTC)
    service = FetchRunService(session)
    first = service.create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(days=2), end=now - timedelta(days=1)),
        )
    )
    IngestionOrchestrator(session, artifact_store).execute(
        first.id,
        OneRecordConnector(
            SourceRecordCandidate(
                external_id="notice-1",
                payload={"id": "notice-1", "version": 1},
                observed_at=now,
                deadline=now + timedelta(days=10),
                attachment_hashes=["old"],
            )
        ),
    )
    second = service.create(
        FetchRunCreate(
            source_id=source.id,
            window=TimeWindow(start=now - timedelta(days=1), end=now),
        )
    )
    IngestionOrchestrator(session, artifact_store).execute(
        second.id,
        OneRecordConnector(
            SourceRecordCandidate(
                external_id="notice-1",
                payload={"id": "notice-1", "version": 2, "status": "cancelled"},
                observed_at=now,
                revoked=True,
                deadline=now + timedelta(days=5),
                attachment_hashes=["new"],
            )
        ),
    )
    events = session.scalars(
        select(ChangeEventRow).where(ChangeEventRow.source_id == source.id)
    ).all()
    assert {event.change_type for event in events} == {
        "added",
        "revoked",
        "deadline_changed",
        "attachment_changed",
    }


def test_generic_payload_revision_emits_updated(session, source_factory, artifact_store):
    source = source_factory(key="generic-update")
    now = datetime.now(UTC)
    service = FetchRunService(session)
    for index, value in enumerate(["old", "new"]):
        run = service.create(
            FetchRunCreate(
                source_id=source.id,
                window=TimeWindow(
                    start=now + timedelta(hours=index),
                    end=now + timedelta(hours=index + 1),
                ),
            )
        )
        IngestionOrchestrator(session, artifact_store).execute(
            run.id,
            OneRecordConnector(
                SourceRecordCandidate(
                    external_id="same", payload={"id": "same", "value": value}, observed_at=now
                )
            ),
        )
    event_types = session.scalars(select(ChangeEventRow.change_type)).all()
    assert set(event_types) == {"added", "updated"}
