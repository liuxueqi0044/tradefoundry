from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.connectors.factory import ConnectorFactory
from tradefoundry.ingestion.contracts import ReplayReport, ReplayRequest, RunStatus, SourceKind
from tradefoundry.ingestion.models import (
    FetchRunRow,
    RecordObservationRow,
    ReplayBatchRow,
    SourceRow,
)
from tradefoundry.ingestion.runs import FetchRunService, IngestionOrchestrator


class ReplayService:
    def __init__(
        self,
        session: Session,
        artifact_store: FileSystemArtifactStore,
        connector_factory: ConnectorFactory | None = None,
    ):
        self.session = session
        self.artifact_store = artifact_store
        self.connector_factory = connector_factory or ConnectorFactory()

    def replay(
        self, request: ReplayRequest, connector: BaseConnector | None = None
    ) -> ReplayReport:
        key = FetchRunService.window_key(request.window)
        original = self.session.scalar(
            select(FetchRunRow)
            .where(
                FetchRunRow.source_id == request.source_id,
                FetchRunRow.window_key == key,
                FetchRunRow.status == RunStatus.SUCCEEDED.value,
            )
            .order_by(FetchRunRow.attempt)
            .limit(1)
        )
        if original is None:
            raise LookupError("no successful original run exists for the requested window")
        selected = connector
        if selected is None:
            source = self.session.get(SourceRow, request.source_id)
            if source is None:
                raise LookupError(request.source_id)
            selected = self.connector_factory.get(SourceKind(source.kind))
        if request.connector_version and request.connector_version != selected.version:
            raise ValueError(
                f"requested connector version {request.connector_version} is not installed; "
                f"available version is {selected.version}"
            )
        replay_run = FetchRunService(self.session).rerun(original.id)
        completed = IngestionOrchestrator(
            self.session, self.artifact_store, self.connector_factory
        ).execute(replay_run.id, selected)
        if completed.status != RunStatus.SUCCEEDED:
            raise RuntimeError(f"replay run failed: {completed.error}")
        original_hashes = self._hashes(original.id)
        replay_hashes = self._hashes(completed.id)
        diff = {
            "added_hashes": sorted(replay_hashes - original_hashes),
            "missing_hashes": sorted(original_hashes - replay_hashes),
            "unchanged_hashes": sorted(original_hashes & replay_hashes),
        }
        row = ReplayBatchRow(
            id=str(uuid4()),
            source_id=request.source_id,
            original_run_id=original.id,
            replay_run_id=completed.id,
            connector_version=selected.version,
            diff_json=diff,
        )
        self.session.add(row)
        self.session.commit()
        return ReplayReport(
            id=row.id,
            source_id=row.source_id,
            original_run_id=row.original_run_id,
            replay_run_id=row.replay_run_id,
            created_at=row.created_at,
            **diff,
        )

    def _hashes(self, run_id: str) -> set[str]:
        rows = self.session.scalars(
            select(RecordObservationRow.payload_hash).where(
                RecordObservationRow.fetch_run_id == run_id
            )
        ).all()
        return set(rows)
