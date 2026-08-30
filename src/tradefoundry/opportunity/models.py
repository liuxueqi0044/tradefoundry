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
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.ingestion.models import utcnow


class WorldEventRow(Base):
    __tablename__ = "opportunity_world_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    location_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    reliability: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    facts_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorldEventClaimRow(Base):
    __tablename__ = "opportunity_world_event_claims"
    __table_args__ = (UniqueConstraint("event_id", "claim_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorldEventSubjectRow(Base):
    __tablename__ = "opportunity_world_event_subjects"
    __table_args__ = (UniqueConstraint("event_id", "entity_id", "role", "claim_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorldEventProductRow(Base):
    __tablename__ = "opportunity_world_event_products"
    __table_args__ = (UniqueConstraint("event_id", "product_concept_id", "claim_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    certainty: Mapped[float] = mapped_column(Float, nullable=False)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventSignalRow(Base):
    __tablename__ = "opportunity_event_signals"
    __table_args__ = (UniqueConstraint("event_id", "signal_type", "classifier_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpportunityTemplateRow(Base):
    __tablename__ = "opportunity_templates"
    __table_args__ = (UniqueConstraint("template_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(100), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    event_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    signal_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    country_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    product_concept_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_claim_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    forbidden_conditions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    product_need_rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TemplateStateChangeRow(Base):
    __tablename__ = "opportunity_template_state_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_templates.id", ondelete="RESTRICT"), index=True
    )
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductNeedRow(Base):
    __tablename__ = "opportunity_product_needs"
    __table_args__ = (
        UniqueConstraint("event_id", "template_id", "product_concept_id", "derivation_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    template_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_templates.id", ondelete="RESTRICT"), index=True
    )
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    basis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[str] = mapped_column(Text, nullable=False)
    derivation_chain_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    supporting_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    derivation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParticipantCandidateRow(Base):
    __tablename__ = "opportunity_participant_candidates"
    __table_args__ = (UniqueConstraint("event_id", "entity_id", "role", "discovery_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    hop_distance: Mapped[int] = mapped_column(Integer, nullable=False)
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    discovery_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RouteCandidateRow(Base):
    __tablename__ = "opportunity_route_candidates"
    __table_args__ = (
        UniqueConstraint("event_id", "route_type", "generator_version", "input_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_world_events.id", ondelete="RESTRICT"), index=True
    )
    route_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    feasibility: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    participant_candidate_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    missing_requirements_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    generator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradeHypothesisRow(Base):
    __tablename__ = "opportunity_trade_hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    event_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_templates.id", ondelete="RESTRICT"), index=True
    )
    product_need_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    buyer_candidate_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    supplier_candidate_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    route_candidate_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    fact_assertions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    inference_assertions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    supporting_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    counter_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risks_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    probability_low: Mapped[float] = mapped_column(Float, nullable=False)
    probability_high: Mapped[float] = mapped_column(Float, nullable=False)
    probe_actions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    stop_conditions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    numeric_assertions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    compiler_version: Mapped[str] = mapped_column(String(100), nullable=False)
    audit_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HypothesisAuditRow(Base):
    __tablename__ = "opportunity_hypothesis_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_trade_hypotheses.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    auditor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DealCellIssuanceRow(Base):
    __tablename__ = "opportunity_deal_cell_issuance_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_trade_hypotheses.id", ondelete="RESTRICT"), index=True
    )
    command_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    deal_cell_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompilerRunRow(Base):
    __tablename__ = "opportunity_compiler_runs"
    __table_args__ = (
        Index("ix_opportunity_compiler_run_replay", "input_hash", "compiler_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
