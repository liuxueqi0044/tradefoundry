from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.ingestion.models import utcnow


class EntityRow(Base):
    __tablename__ = "master_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    canonical_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    risk_tier: Mapped[str] = mapped_column(String(30), default="normal", nullable=False)
    frozen_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EntityAliasRow(Base):
    __tablename__ = "master_entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_value", "source_claim_id"),
        Index("ix_master_alias_normalized", "normalized_value", "language"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(30), default="name", nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityAttributeRow(Base):
    __tablename__ = "master_entity_attributes"
    __table_args__ = (
        UniqueConstraint("entity_id", "field_name", "source_claim_id", "raw_hash"),
        Index("ix_master_attribute_entity_field", "entity_id", "field_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    normalized_value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityIdentifierRow(Base):
    __tablename__ = "master_entity_identifiers"
    __table_args__ = (
        UniqueConstraint("entity_id", "scheme", "normalized_value", "source_claim_id"),
        Index("ix_master_identifier_lookup", "scheme", "normalized_value"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    scheme: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str] = mapped_column(String(20), default="strong", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DistinctEntityPairRow(Base):
    __tablename__ = "master_distinct_entity_pairs"
    __table_args__ = (UniqueConstraint("left_entity_id", "right_entity_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    left_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    right_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdentityConflictRow(Base):
    __tablename__ = "master_identity_conflicts"
    __table_args__ = (
        UniqueConstraint("scheme", "normalized_value", "left_entity_id", "right_entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scheme: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    left_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    right_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MergeCommandRow(Base):
    __tablename__ = "master_merge_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    winner_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    loser_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    decision_source: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="applied", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SplitCommandRow(Base):
    __tablename__ = "master_split_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    previous_canonical_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT")
    )
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchRunRow(Base):
    __tablename__ = "master_match_runs"
    __table_args__ = (UniqueConstraint("query_entity_id", "model_version", "snapshot_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchCandidateRow(Base):
    __tablename__ = "master_match_candidates"
    __table_args__ = (UniqueConstraint("run_id", "candidate_entity_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("master_match_runs.id", ondelete="RESTRICT"), index=True
    )
    query_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    candidate_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    probability: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    merge_command_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_merge_commands.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductConceptRow(Base):
    __tablename__ = "master_product_concepts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), unique=True
    )
    preferred_label: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_label: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductSynonymRow(Base):
    __tablename__ = "master_product_synonyms"
    __table_args__ = (
        UniqueConstraint("concept_id", "normalized_label", "language", "source_claim_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_label: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductCodeMappingRow(Base):
    __tablename__ = "master_product_code_mappings"
    __table_args__ = (
        UniqueConstraint("concept_id", "scheme", "code", "source_claim_id"),
        Index("ix_master_product_code", "scheme", "code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductSpecificationRow(Base):
    __tablename__ = "master_product_specifications"
    __table_args__ = (UniqueConstraint("concept_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    specification_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductRequirementRow(Base):
    __tablename__ = "master_product_requirements"
    __table_args__ = (UniqueConstraint("specification_id", "requirement_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    specification_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_specifications.id", ondelete="RESTRICT"), index=True
    )
    requirement_key: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    normalized_value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RelationRow(Base):
    __tablename__ = "master_relations"
    __table_args__ = (
        UniqueConstraint(
            "subject_entity_id", "relation_type", "object_entity_id", "evidence_claim_id"
        ),
        Index("ix_master_relation_subject_type", "subject_entity_id", "relation_type"),
        Index("ix_master_relation_object_type", "object_entity_id", "relation_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    evidence_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
