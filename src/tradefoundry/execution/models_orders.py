from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.execution.common import utcnow

MONEY = Numeric(19, 4)
QUANTITY = Numeric(19, 6)


class ErpMappingRow(Base):
    __tablename__ = "execution_erp_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "resource_type", "internal_id"),
        UniqueConstraint("provider", "resource_type", "external_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    internal_id: Mapped[str] = mapped_column(String(200), index=True)
    external_id: Mapped[str] = mapped_column(String(240), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionOutboxRow(Base):
    __tablename__ = "execution_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(60), index=True)
    topic: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExecutionOutboxAttemptRow(Base):
    __tablename__ = "execution_outbox_attempts"
    __table_args__ = (UniqueConstraint("outbox_id", "attempt_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    outbox_id: Mapped[str] = mapped_column(
        ForeignKey("execution_outbox.id", ondelete="RESTRICT"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderCommandRow(Base):
    __tablename__ = "execution_order_commands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    order_kind: Mapped[str] = mapped_column(String(20), index=True)
    customer_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    supplier_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    item_ref: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str] = mapped_column(String(30))
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    commitment_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    commitment_evidence_ids_json: Mapped[list[str]] = mapped_column(JSON)
    policy_decision_id: Mapped[str] = mapped_column(
        ForeignKey("risk_policy_decisions.id", ondelete="RESTRICT"), index=True
    )
    approval_request_id: Mapped[str] = mapped_column(
        ForeignKey("risk_approval_requests.id", ondelete="RESTRICT"), index=True
    )
    token_id: Mapped[str] = mapped_column(
        ForeignKey("risk_execution_tokens.id", ondelete="RESTRICT"), index=True
    )
    params_hash: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), index=True)
    outbox_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_outbox.id", ondelete="RESTRICT"), index=True
    )
    external_order_id: Mapped[str | None] = mapped_column(String(240), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderSnapshotRow(Base):
    __tablename__ = "execution_order_snapshots"
    __table_args__ = (UniqueConstraint("provider", "external_event_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    external_event_id: Mapped[str] = mapped_column(String(240), index=True)
    external_order_id: Mapped[str] = mapped_column(String(240), index=True)
    order_kind: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(60))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconciliation_status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionReviewIssueRow(Base):
    __tablename__ = "execution_review_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_ref: Mapped[str] = mapped_column(String(300), index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FulfillmentMilestoneRow(Base):
    __tablename__ = "execution_fulfillment_milestones"
    __table_args__ = (UniqueConstraint("shipment_id", "milestone_key", "version_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(160), index=True)
    milestone_key: Mapped[str] = mapped_column(String(100), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    actual_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str] = mapped_column(String(30))
    late_days: Mapped[int | None] = mapped_column(Integer)
    delivery_status: Mapped[str] = mapped_column(String(30), index=True)
    evidence_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    evidence_fragment_ids_json: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShipmentDocumentRow(Base):
    __tablename__ = "execution_shipment_documents"
    __table_args__ = (UniqueConstraint("shipment_id", "document_type", "version_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(160), index=True)
    document_type: Mapped[str] = mapped_column(String(40), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    storage_ref: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(128))
    evidence_claim_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    evidence_fragment_ids_json: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    related_document_versions_json: Mapped[dict[str, int]] = mapped_column(JSON)
    sensitive_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
