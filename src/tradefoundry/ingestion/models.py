from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class SourceRow(Base):
    __tablename__ = "ingest_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceVersionRow(Base):
    __tablename__ = "ingest_source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_sources.id", ondelete="RESTRICT"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    access_url: Mapped[str | None] = mapped_column(Text)
    access_method: Mapped[str] = mapped_column(String(100), nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(100))
    sla_hours: Mapped[int | None] = mapped_column(Integer)
    license_name: Mapped[str | None] = mapped_column(String(200))
    license_url: Mapped[str | None] = mapped_column(Text)
    terms_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commercial_use_allowed: Mapped[bool | None] = mapped_column(Boolean)
    retention_allowed: Mapped[bool | None] = mapped_column(Boolean)
    redistribution_allowed: Mapped[bool | None] = mapped_column(Boolean)
    connector_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArtifactBlobRow(Base):
    __tablename__ = "ingest_artifact_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArtifactObservationRow(Base):
    __tablename__ = "ingest_artifact_observations"
    __table_args__ = (UniqueConstraint("source_id", "fetch_run_id", "sha256", "source_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    sha256: Mapped[str] = mapped_column(ForeignKey("ingest_artifact_blobs.sha256"), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceRecordRow(Base):
    __tablename__ = "ingest_source_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", "payload_hash"),
        Index(
            "uq_record_one_current",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(ForeignKey("ingest_artifact_blobs.sha256"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connector_version: Mapped[str] = mapped_column(String(100), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachment_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    relation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecordObservationRow(Base):
    __tablename__ = "ingest_record_observations"
    __table_args__ = (
        UniqueConstraint("fetch_run_id", "external_id", "payload_hash"),
        Index("ix_record_observation_run", "fetch_run_id", "payload_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FetchRunRow(Base):
    __tablename__ = "ingest_fetch_runs"
    __table_args__ = (UniqueConstraint("source_id", "window_key", "attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    cursor_before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cursor_after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_fetch_runs.id"))


class QuarantineRow(Base):
    __tablename__ = "ingest_quarantine"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeEventRow(Base):
    __tablename__ = "ingest_change_events"
    __table_args__ = (UniqueConstraint("fetch_run_id", "external_id", "change_type", "new_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_hash: Mapped[str | None] = mapped_column(String(64))
    new_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityAssessmentRow(Base):
    __tablename__ = "ingest_quality_assessments"
    __table_args__ = (UniqueConstraint("fetch_run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    anomalies: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataQualityAlertRow(Base):
    __tablename__ = "ingest_data_quality_alerts"
    __table_args__ = (UniqueConstraint("fetch_run_id", "anomaly_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), index=True)
    anomaly_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReplayBatchRow(Base):
    __tablename__ = "ingest_replay_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("ingest_sources.id"), index=True)
    original_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_fetch_runs.id"))
    replay_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_fetch_runs.id"), unique=True)
    connector_version: Mapped[str] = mapped_column(String(100), nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
