from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.ingestion.models import utcnow

MONEY = Numeric(19, 4)
QUANTITY = Numeric(19, 6)


class SupplierProfileRow(Base):
    __tablename__ = "bilateral_supplier_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), unique=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SupplierProfileEvidenceRow(Base):
    __tablename__ = "bilateral_supplier_profile_evidence"
    __table_args__ = (UniqueConstraint("supplier_profile_id", "field_path", "source_claim_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(160), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierCapabilityRow(Base):
    __tablename__ = "bilateral_supplier_capabilities"
    __table_args__ = (
        UniqueConstraint("supplier_profile_id", "product_concept_id", "source_claim_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    specifications_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    certifications_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    capacity_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierCandidateRow(Base):
    __tablename__ = "bilateral_supplier_candidates"
    __table_args__ = (UniqueConstraint("route_id", "supplier_profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_basis_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    source_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    missing_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    displayed_price_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    displayed_price_is_quote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whitelist_policy_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    whitelisted_by: Mapped[str | None] = mapped_column(String(200))
    whitelisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="candidate", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RfqVersionRow(Base):
    __tablename__ = "bilateral_rfq_versions"
    __table_args__ = (UniqueConstraint("route_id", "rfq_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    rfq_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    requirement_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str | None] = mapped_column(String(40))
    destination_country: Mapped[str] = mapped_column(String(2), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(3))
    requested_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    questions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unresolved_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content_zh: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    finalized_by: Mapped[str | None] = mapped_column(String(200))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SendTokenRow(Base):
    __tablename__ = "bilateral_send_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    action_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    recipient_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboundMessageRow(Base):
    __tablename__ = "bilateral_outbound_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    token_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_send_tokens.id", ondelete="RESTRICT"), unique=True
    )
    gateway_name: Mapped[str] = mapped_column(String(80), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    sent_by: Mapped[str] = mapped_column(String(200), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierQuoteRow(Base):
    __tablename__ = "bilateral_supplier_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    rfq_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("bilateral_rfq_versions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intake_format: Mapped[str] = mapped_column(String(30), nullable=False)
    raw_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    price_unit: Mapped[str | None] = mapped_column(String(40))
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    moq_quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    moq_unit: Mapped[str | None] = mapped_column(String(40))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    tax_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(String(3))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    specifications_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    uncertain_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuoteComparisonRow(Base):
    __tablename__ = "bilateral_quote_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    target_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    target_incoterm: Mapped[str] = mapped_column(String(3), nullable=False)
    conversion_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rows_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    specification_differences_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    incomparable_quote_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierPerformanceEventRow(Base):
    __tablename__ = "bilateral_supplier_performance_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    predicted_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actual_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(30), index=True)
    evidence_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierPerformanceSnapshotRow(Base):
    __tablename__ = "bilateral_supplier_performance_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_supplier_profiles.id", ondelete="RESTRICT"), index=True
    )
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_actual_count: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    confidence_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BuyerProfileRow(Base):
    __tablename__ = "bilateral_buyer_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), unique=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContactRow(Base):
    __tablename__ = "bilateral_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContactPointRow(Base):
    __tablename__ = "bilateral_contact_points"
    __table_args__ = (UniqueConstraint("contact_id", "channel", "normalized_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    lawful_basis: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContactAffiliationRow(Base):
    __tablename__ = "bilateral_contact_affiliations"
    __table_args__ = (UniqueConstraint("contact_id", "buyer_profile_id", "role", "valid_from"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    buyer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_buyer_profiles.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SuppressionRow(Base):
    __tablename__ = "bilateral_suppressions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EligibilityDecisionRow(Base):
    __tablename__ = "bilateral_eligibility_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(2), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    blockers_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    policy_decision_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    policy_version: Mapped[str | None] = mapped_column(String(120))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageDraftRow(Base):
    __tablename__ = "bilateral_message_drafts"
    __table_args__ = (UniqueConstraint("route_id", "draft_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    buyer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_buyer_profiles.id", ondelete="RESTRICT"), index=True
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    eligibility_decision_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_eligibility_decisions.id", ondelete="RESTRICT"), index=True
    )
    draft_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_context_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    capability_context_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    context_claim_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_confirmations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prohibited_findings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InteractionRow(Base):
    __tablename__ = "bilateral_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_message_id: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    thread_key: Mapped[str | None] = mapped_column(String(300), index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    raw_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attachment_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    link_method: Mapped[str] = mapped_column(String(40), nullable=False)
    link_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InteractionReviewQueueRow(Base):
    __tablename__ = "bilateral_interaction_review_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interaction_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_interactions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_routes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntentAssessmentRow(Base):
    __tablename__ = "bilateral_intent_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interaction_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_interactions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(120), nullable=False)
    intent: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    questions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    objections_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualificationSnapshotRow(Base):
    __tablename__ = "bilateral_qualification_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    quantity_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    specification_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    budget_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timing_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    authority_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    procurement_process_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    missing_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_interaction_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConstraintAssessmentRow(Base):
    __tablename__ = "bilateral_constraint_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    qualification_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_qualification_snapshots.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    matrix_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    conflicts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    candidate_solutions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    route_reassessment_required: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BuyerQuoteVersionRow(Base):
    __tablename__ = "bilateral_buyer_quote_versions"
    __table_args__ = (UniqueConstraint("route_id", "quote_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    quote_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_scenario_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    cost_scenario_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    calculator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    cost_status: Mapped[str] = mapped_column(String(30), nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin_rate: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    selling_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NegotiationTermVersionRow(Base):
    __tablename__ = "bilateral_negotiation_term_versions"
    __table_args__ = (UniqueConstraint("route_id", "term_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    term_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    floor_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    floor_violations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    counterparty_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MeetingImportRow(Base):
    __tablename__ = "bilateral_meeting_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    external_ref: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BilateralTaskRow(Base):
    __tablename__ = "bilateral_tasks"
    __table_args__ = (UniqueConstraint("meeting_import_id", "task_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_import_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_meeting_imports.id", ondelete="RESTRICT"), index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    task_key: Mapped[str] = mapped_column(String(160), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="proposed", nullable=False, index=True)
    action_proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
