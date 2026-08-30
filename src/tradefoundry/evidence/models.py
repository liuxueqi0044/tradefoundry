from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
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
from tradefoundry.ingestion.models import utcnow


class EvidenceDocumentRow(Base):
    __tablename__ = "evidence_documents"
    __table_args__ = (UniqueConstraint("logical_document_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    logical_document_id: Mapped[str] = mapped_column(String(200), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    artifact_sha256: Mapped[str | None] = mapped_column(
        ForeignKey("ingest_artifact_blobs.sha256", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    declared_media_type: Mapped[str | None] = mapped_column(String(200))
    detected_media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    security_status: Mapped[str] = mapped_column(String(40), nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentConversionRow(Base):
    __tablename__ = "evidence_conversions"
    __table_args__ = (UniqueConstraint("document_id", "converter_name", "converter_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="RESTRICT"), index=True
    )
    converter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    converter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    markdown: Mapped[str] = mapped_column(Text, default="")
    normalized_document_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceFragmentRow(Base):
    __tablename__ = "evidence_fragments"
    __table_args__ = (
        UniqueConstraint("conversion_id", "fragment_key"),
        Index("ix_evidence_fragment_document_page", "document_id", "page_no"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="RESTRICT"), index=True
    )
    conversion_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_conversions.id", ondelete="RESTRICT"), index=True
    )
    fragment_key: Mapped[str] = mapped_column(String(500), nullable=False)
    fragment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    section_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    table_cell_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionSchemaRow(Base):
    __tablename__ = "evidence_extraction_schemas"
    __table_args__ = (
        UniqueConstraint("schema_key", "version_no"),
        Index(
            "uq_evidence_one_active_schema",
            "schema_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_key: Mapped[str] = mapped_column(String(100), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    field_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    instructions: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionRunRow(Base):
    __tablename__ = "evidence_extraction_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="RESTRICT"), index=True
    )
    schema_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_extraction_schemas.id", ondelete="RESTRICT"), index=True
    )
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    raw_output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConflictGroupRow(Base):
    __tablename__ = "evidence_conflict_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_key: Mapped[str] = mapped_column(String(300), index=True)
    field_path: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimRow(Base):
    __tablename__ = "evidence_claims"
    __table_args__ = (Index("ix_evidence_claim_subject_field", "subject_key", "field_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="RESTRICT"), index=True
    )
    extraction_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    schema_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_extraction_schemas.id", ondelete="RESTRICT"), index=True
    )
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)
    field_path: Mapped[str] = mapped_column(String(300), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    normalized_value_json: Mapped[Any | None] = mapped_column(JSON)
    normalization_status: Mapped[str] = mapped_column(String(40), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(3))
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    method_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    supersedes_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT")
    )
    conflict_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_conflict_groups.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimEvidenceRow(Base):
    __tablename__ = "evidence_claim_links"
    __table_args__ = (UniqueConstraint("claim_id", "fragment_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    fragment_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_fragments.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewDecisionRow(Base):
    __tablename__ = "evidence_review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    resulting_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT")
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
