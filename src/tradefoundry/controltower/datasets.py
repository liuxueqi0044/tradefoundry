from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    utcnow,
)
from tradefoundry.controltower.contracts import DatasetSyncCreate, DatasetSyncFailure
from tradefoundry.controltower.models import (
    ComplianceDatasetRow,
    ComplianceEntryRow,
    ComplianceSyncAttemptRow,
)
from tradefoundry.ingestion.hashing import payload_hash


class ComplianceDatasetService:
    """Activates complete immutable snapshots; failed syncs never replace the active one."""

    def __init__(self, session: Session):
        self.session = session

    def sync(self, request: DatasetSyncCreate) -> ComplianceDatasetRow:
        request_hash = request_fingerprint({"operation": "risk.dataset.sync"}, request)
        existing = idempotent_row(
            self.session, ComplianceSyncAttemptRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            if existing.status != "success" or not existing.resulting_dataset_id:
                raise ValueError("the idempotent dataset sync previously failed")
            return self.session.get(ComplianceDatasetRow, existing.resulting_dataset_id)
        external_ids = [entry.external_id for entry in request.entries]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("compliance dataset external IDs must be unique")
        active = self.active(request.dataset_key, required=False)
        attempt = ComplianceSyncAttemptRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            dataset_key=request.dataset_key,
            source_uri=request.source_uri,
            previous_active_dataset_id=active.id if active else None,
            resulting_dataset_id=None,
            status="running",
            error_message=None,
        )
        self.session.add(attempt)
        self.session.flush()
        latest = self.session.scalar(
            select(ComplianceDatasetRow)
            .where(ComplianceDatasetRow.dataset_key == request.dataset_key)
            .order_by(ComplianceDatasetRow.version_no.desc())
        )
        entries_snapshot = [entry.model_dump(mode="json") for entry in request.entries]
        content_hash = payload_hash(
            {
                "dataset_key": request.dataset_key,
                "dataset_type": request.dataset_type,
                "publisher": request.publisher,
                "published_at": request.published_at.isoformat(),
                "effective_from": (
                    request.effective_from.isoformat() if request.effective_from else None
                ),
                "effective_to": (
                    request.effective_to.isoformat() if request.effective_to else None
                ),
                "entries": entries_snapshot,
            }
        )
        dataset = ComplianceDatasetRow(
            id=new_id(),
            dataset_key=request.dataset_key,
            version_no=1 if latest is None else latest.version_no + 1,
            dataset_type=request.dataset_type,
            source_uri=request.source_uri,
            publisher=request.publisher,
            published_at=request.published_at,
            effective_from=request.effective_from,
            effective_to=request.effective_to,
            content_hash=content_hash,
            license_name=request.license_name,
            entry_count=len(request.entries),
            status="active",
            activated_at=utcnow(),
        )
        self.session.add(dataset)
        self.session.flush()
        for entry in request.entries:
            snapshot = entry.model_dump(mode="json")
            self.session.add(
                ComplianceEntryRow(
                    id=new_id(),
                    dataset_id=dataset.id,
                    external_id=entry.external_id,
                    entry_type=entry.entry_type,
                    names_json=entry.names,
                    identifiers_json=entry.identifiers,
                    countries_json=sorted({country.upper() for country in entry.countries}),
                    programs_json=entry.programs,
                    fields_json=entry.fields,
                    effective_from=entry.effective_from,
                    effective_to=entry.effective_to,
                    content_hash=payload_hash(snapshot),
                )
            )
        if active is not None:
            active.status = "superseded"
        attempt.status = "success"
        attempt.resulting_dataset_id = dataset.id
        attempt.completed_at = utcnow()
        self.session.commit()
        return dataset

    def record_failure(self, request: DatasetSyncFailure) -> ComplianceSyncAttemptRow:
        request_hash = request_fingerprint({"operation": "risk.dataset.sync_failure"}, request)
        existing = idempotent_row(
            self.session, ComplianceSyncAttemptRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        active = self.active(request.dataset_key, required=False)
        row = ComplianceSyncAttemptRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            dataset_key=request.dataset_key,
            source_uri=request.source_uri,
            previous_active_dataset_id=active.id if active else None,
            resulting_dataset_id=None,
            status="failed",
            error_message=request.error_message,
            completed_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def active(self, dataset_key: str, *, required: bool = True) -> ComplianceDatasetRow | None:
        row = self.session.scalar(
            select(ComplianceDatasetRow).where(
                ComplianceDatasetRow.dataset_key == dataset_key,
                ComplianceDatasetRow.status == "active",
            )
        )
        if row is None and required:
            raise LookupError(f"active compliance dataset {dataset_key} was not found")
        return row

    def entries(self, dataset_id: str) -> list[ComplianceEntryRow]:
        return list(
            self.session.scalars(
                select(ComplianceEntryRow)
                .where(ComplianceEntryRow.dataset_id == dataset_id)
                .order_by(ComplianceEntryRow.external_id)
            )
        )
