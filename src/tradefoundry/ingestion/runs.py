from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.changes import ChangeDetector
from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.connectors.factory import ConnectorFactory
from tradefoundry.ingestion.contracts import (
    ConnectorContext,
    FetchRunCreate,
    FetchRunView,
    RunStatus,
    SourceKind,
    TimeWindow,
)
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.ingestion.models import (
    ArtifactBlobRow,
    ArtifactObservationRow,
    ChangeEventRow,
    FetchRunRow,
    QuarantineRow,
    RecordObservationRow,
    SourceRecordRow,
    SourceRow,
    SourceVersionRow,
)
from tradefoundry.ingestion.quality import QualityService

ACTIVE_RUN_STATES = {
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.PAUSED.value,
    RunStatus.CANCEL_REQUESTED.value,
}


class RunNotFoundError(LookupError):
    pass


class InvalidRunTransition(ValueError):
    pass


class FetchRunService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: FetchRunCreate) -> FetchRunView:
        source = self._active_source(request.source_id)
        key = self.window_key(request.window)
        existing = self.session.scalar(
            select(FetchRunRow).where(
                FetchRunRow.source_id == source.id,
                FetchRunRow.window_key == key,
                FetchRunRow.attempt == 1,
            )
        )
        if existing:
            return FetchRunView.model_validate(existing)
        row = FetchRunRow(
            id=str(uuid4()),
            source_id=source.id,
            status=RunStatus.QUEUED.value,
            window_start=request.window.start,
            window_end=request.window.end,
            window_key=key,
            attempt=1,
            priority=request.priority,
            cursor_before=request.cursor,
            metrics={},
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(FetchRunRow).where(
                    FetchRunRow.source_id == source.id,
                    FetchRunRow.window_key == key,
                    FetchRunRow.attempt == 1,
                )
            )
            if existing is None:
                raise
            return FetchRunView.model_validate(existing)
        return FetchRunView.model_validate(row)

    def rerun(self, run_id: str) -> FetchRunView:
        return self._new_attempt(run_id, resume=False)

    def retry(self, run_id: str) -> FetchRunView:
        parent = self._run(run_id)
        if parent.status not in {RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
            raise InvalidRunTransition(f"cannot retry {parent.status}")
        return self._new_attempt(run_id, resume=True)

    def _new_attempt(self, run_id: str, *, resume: bool) -> FetchRunView:
        parent = self._run(run_id)
        attempt = (
            self.session.scalar(
                select(func.max(FetchRunRow.attempt)).where(
                    FetchRunRow.source_id == parent.source_id,
                    FetchRunRow.window_key == parent.window_key,
                )
            )
            or 0
        )
        row = FetchRunRow(
            id=str(uuid4()),
            source_id=parent.source_id,
            status=RunStatus.QUEUED.value,
            window_start=parent.window_start,
            window_end=parent.window_end,
            window_key=parent.window_key,
            attempt=attempt + 1,
            priority=parent.priority,
            cursor_before=(parent.cursor_after or parent.cursor_before)
            if resume
            else parent.cursor_before,
            metrics={},
            parent_run_id=parent.id,
        )
        self.session.add(row)
        self.session.commit()
        return FetchRunView.model_validate(row)

    def pause(self, run_id: str) -> FetchRunView:
        row = self._run(run_id)
        if row.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
            raise InvalidRunTransition(f"cannot pause {row.status}")
        row.status = RunStatus.PAUSED.value
        self.session.commit()
        return FetchRunView.model_validate(row)

    def resume(self, run_id: str) -> FetchRunView:
        row = self._run(run_id)
        if row.status != RunStatus.PAUSED.value:
            raise InvalidRunTransition(f"cannot resume {row.status}")
        row.status = RunStatus.QUEUED.value
        self.session.commit()
        return FetchRunView.model_validate(row)

    def cancel(self, run_id: str) -> FetchRunView:
        row = self._run(run_id)
        if row.status in {RunStatus.QUEUED.value, RunStatus.PAUSED.value}:
            row.status = RunStatus.CANCELLED.value
            row.finished_at = datetime.now(UTC)
        elif row.status == RunStatus.RUNNING.value:
            row.status = RunStatus.CANCEL_REQUESTED.value
        else:
            raise InvalidRunTransition(f"cannot cancel {row.status}")
        self.session.commit()
        return FetchRunView.model_validate(row)

    def get(self, run_id: str) -> FetchRunView:
        return FetchRunView.model_validate(self._run(run_id))

    def row(self, run_id: str) -> FetchRunRow:
        return self._run(run_id)

    @staticmethod
    def window_key(window: TimeWindow) -> str:
        return payload_hash({"start": window.start.isoformat(), "end": window.end.isoformat()})

    def _run(self, run_id: str) -> FetchRunRow:
        row = self.session.get(FetchRunRow, run_id)
        if row is None:
            raise RunNotFoundError(run_id)
        return row

    def _active_source(self, source_id: str) -> SourceRow:
        source = self.session.get(SourceRow, source_id)
        if source is None:
            raise LookupError(source_id)
        if not source.active:
            raise ValueError("source is not active")
        return source


class IngestionOrchestrator:
    def __init__(
        self,
        session: Session,
        artifact_store: FileSystemArtifactStore,
        connector_factory: ConnectorFactory | None = None,
    ):
        self.session = session
        self.artifact_store = artifact_store
        self.connector_factory = connector_factory or ConnectorFactory()
        self.change_detector = ChangeDetector()

    def execute(self, run_id: str, connector: BaseConnector | None = None) -> FetchRunView:
        run = self._run(run_id)
        if run.status == RunStatus.PAUSED.value:
            return FetchRunView.model_validate(run)
        if run.status != RunStatus.QUEUED.value:
            raise InvalidRunTransition(f"cannot execute {run.status}")
        source = self.session.get(SourceRow, run.source_id)
        if source is None or not source.active:
            raise ValueError("source is missing or inactive")
        version = self.session.scalar(
            select(SourceVersionRow).where(
                SourceVersionRow.source_id == source.id,
                SourceVersionRow.version_no == source.current_version,
            )
        )
        if version is None:
            raise RuntimeError("source version missing")
        selected = connector or self.connector_factory.get(SourceKind(source.kind))
        context = ConnectorContext(
            source_id=source.id,
            source_key=source.key,
            source_version=version.version_no,
            connector_version=selected.version,
            config=version.connector_config,
            cursor=run.cursor_before,
            window=TimeWindow(start=run.window_start, end=run.window_end),
        )
        run.status = RunStatus.RUNNING.value
        run.started_at = datetime.now(UTC)
        self.session.commit()
        totals: dict[str, Any] = {
            "batches": 0,
            "records_seen": 0,
            "records_inserted": 0,
            "duplicate_records": 0,
            "artifacts_seen": 0,
            "quarantined": 0,
            "changes": 0,
            "max_time_drift_hours": 0.0,
            "field_counts": {},
        }
        try:
            for batch in selected.fetch(context):
                self.session.refresh(run)
                if run.status in {RunStatus.CANCEL_REQUESTED.value, RunStatus.CANCELLED.value}:
                    run.status = RunStatus.CANCELLED.value
                    run.finished_at = datetime.now(UTC)
                    run.metrics = totals
                    self.session.commit()
                    return FetchRunView.model_validate(run)
                if run.status == RunStatus.PAUSED.value:
                    run.metrics = totals
                    self.session.commit()
                    return FetchRunView.model_validate(run)
                artifact_refs = self._persist_artifacts(source.id, run.id, batch.artifacts)
                for item in batch.quarantined:
                    self.session.add(
                        QuarantineRow(
                            id=str(uuid4()),
                            source_id=source.id,
                            fetch_run_id=run.id,
                            reason_code=item.reason_code,
                            message=item.message,
                            payload_json=item.payload,
                        )
                    )
                for candidate in batch.records:
                    self._persist_record(
                        source.id,
                        run.id,
                        selected.version,
                        candidate,
                        artifact_refs,
                        totals,
                    )
                totals["batches"] += 1
                totals["records_seen"] += len(batch.records)
                totals["artifacts_seen"] += len(batch.artifacts)
                totals["quarantined"] += len(batch.quarantined)
                run.cursor_after = batch.next_cursor
                run.metrics = totals
                self.session.commit()
                context.cursor = batch.next_cursor
            run.status = RunStatus.SUCCEEDED.value
            run.finished_at = datetime.now(UTC)
            run.metrics = totals
            self.session.commit()
            QualityService(self.session).assess(run, version.quality_config)
        except Exception as exc:
            self.session.rollback()
            run = self._run(run_id)
            run.status = RunStatus.FAILED.value
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            run.metrics = totals
            self.session.commit()
            QualityService(self.session).assess(run, version.quality_config)
        return FetchRunView.model_validate(run)

    def _persist_artifacts(self, source_id: str, run_id: str, candidates) -> list:
        refs = []
        for candidate in candidates:
            ref = self.artifact_store.put(candidate)
            refs.append(ref)
            if self.session.get(ArtifactBlobRow, ref.sha256) is None:
                self.session.add(
                    ArtifactBlobRow(
                        sha256=ref.sha256,
                        uri=ref.uri,
                        size_bytes=ref.size_bytes,
                        media_type=ref.media_type,
                    )
                )
                self.session.flush()
            observation = self.session.scalar(
                select(ArtifactObservationRow).where(
                    ArtifactObservationRow.source_id == source_id,
                    ArtifactObservationRow.fetch_run_id == run_id,
                    ArtifactObservationRow.sha256 == ref.sha256,
                    ArtifactObservationRow.source_url == candidate.source_url,
                )
            )
            if observation is None:
                self.session.add(
                    ArtifactObservationRow(
                        id=str(uuid4()),
                        source_id=source_id,
                        fetch_run_id=run_id,
                        sha256=ref.sha256,
                        source_url=candidate.source_url,
                        metadata_json=candidate.metadata,
                    )
                )
        return refs

    def _persist_record(
        self,
        source_id,
        run_id,
        connector_version,
        candidate,
        artifact_refs,
        totals,
    ) -> None:
        digest = payload_hash(candidate.payload)
        prior = self.session.scalar(
            select(SourceRecordRow).where(
                SourceRecordRow.source_id == source_id,
                SourceRecordRow.external_id == candidate.external_id,
                SourceRecordRow.is_current.is_(True),
            )
        )
        existing = self.session.scalar(
            select(SourceRecordRow).where(
                SourceRecordRow.source_id == source_id,
                SourceRecordRow.external_id == candidate.external_id,
                SourceRecordRow.payload_hash == digest,
            )
        )
        if existing:
            totals["duplicate_records"] += 1
        else:
            changes = self.change_detector.detect(prior, candidate, digest)
            if prior:
                prior.is_current = False
            artifact_sha = None
            if candidate.artifact_index is not None and candidate.artifact_index < len(
                artifact_refs
            ):
                artifact_sha = artifact_refs[candidate.artifact_index].sha256
            self.session.add(
                SourceRecordRow(
                    id=str(uuid4()),
                    source_id=source_id,
                    fetch_run_id=run_id,
                    external_id=candidate.external_id,
                    payload_hash=digest,
                    payload_json=candidate.payload,
                    artifact_sha256=artifact_sha,
                    observed_at=candidate.observed_at,
                    effective_at=candidate.effective_at,
                    connector_version=connector_version,
                    revoked=candidate.revoked,
                    deadline=candidate.deadline,
                    attachment_hashes=candidate.attachment_hashes,
                    relation_json=candidate.relation,
                    is_current=True,
                )
            )
            for change in changes:
                self.session.add(
                    ChangeEventRow(
                        id=str(uuid4()),
                        source_id=source_id,
                        fetch_run_id=run_id,
                        external_id=candidate.external_id,
                        change_type=change.change_type.value,
                        old_hash=prior.payload_hash if prior else None,
                        new_hash=digest,
                        details_json=change.details,
                    )
                )
            totals["records_inserted"] += 1
            totals["changes"] += len(changes)
        observed = self.session.scalar(
            select(RecordObservationRow).where(
                RecordObservationRow.fetch_run_id == run_id,
                RecordObservationRow.external_id == candidate.external_id,
                RecordObservationRow.payload_hash == digest,
            )
        )
        if observed is None:
            self.session.add(
                RecordObservationRow(
                    id=str(uuid4()),
                    source_id=source_id,
                    fetch_run_id=run_id,
                    external_id=candidate.external_id,
                    payload_hash=digest,
                    observed_at=candidate.observed_at,
                )
            )
        drift_hours = abs((datetime.now(UTC) - candidate.observed_at).total_seconds()) / 3600
        totals["max_time_drift_hours"] = max(totals["max_time_drift_hours"], drift_hours)
        field_counts = totals["field_counts"]
        for field in candidate.payload:
            field_counts[field] = int(field_counts.get(field, 0)) + 1

    def _run(self, run_id: str) -> FetchRunRow:
        row = self.session.get(FetchRunRow, run_id)
        if row is None:
            raise RunNotFoundError(run_id)
        return row
