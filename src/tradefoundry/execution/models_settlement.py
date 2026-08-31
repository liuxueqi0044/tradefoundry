"""Append-only-ish settlement ledger tables for S9.6 through S9.9.

Order ids intentionally reference ``execution_order_commands`` by string FK.
The order module can be imported independently, while PostgreSQL still enforces
the relationship when both modules are installed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.execution.common import MONEY, utcnow

RATE = Numeric(24, 12)


class InvoiceRefRow(Base):
    __tablename__ = "execution_invoice_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    invoice_kind: Mapped[str] = mapped_column(String(20), index=True)
    invoice_ref: Mapped[str] = mapped_column(String(240), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    buyer_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    supplier_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_system: Mapped[str] = mapped_column(String(80), default="erpnext")
    normalized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    normalized_currency: Mapped[str | None] = mapped_column(String(3))
    conversion_ref: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default="issued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReceivablePayableRow(Base):
    __tablename__ = "execution_receivable_payables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("execution_invoice_refs.id", ondelete="RESTRICT"), unique=True, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    account_kind: Mapped[str] = mapped_column(String(20), index=True)
    original_amount: Mapped[Decimal] = mapped_column(MONEY)
    original_currency: Mapped[str] = mapped_column(String(3))
    outstanding_amount: Mapped[Decimal] = mapped_column(MONEY)
    normalized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    normalized_currency: Mapped[str | None] = mapped_column(String(3))
    conversion_ref: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettlementDiscrepancyRow(Base):
    __tablename__ = "execution_settlement_discrepancies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    subject_type: Mapped[str] = mapped_column(String(40), index=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    expected_amount: Mapped[Decimal] = mapped_column(MONEY)
    actual_amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    difference: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(Text)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentRefRow(Base):
    __tablename__ = "execution_payment_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    payment_ref: Mapped[str] = mapped_column(String(240), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payer_ref: Mapped[str | None] = mapped_column(String(200))
    bank_ref: Mapped[str | None] = mapped_column(String(240), index=True)
    bank_reconciliation_ref: Mapped[str | None] = mapped_column(String(240), index=True)
    bank_reconciliation_evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    bank_reconciled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    fee_currency: Mapped[str] = mapped_column(String(3))
    fx_difference: Mapped[Decimal] = mapped_column(MONEY, default=0)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_system: Mapped[str] = mapped_column(String(80), default="erpnext")
    normalized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    normalized_currency: Mapped[str | None] = mapped_column(String(3))
    conversion_ref: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default="unallocated", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentAllocationRow(Base):
    __tablename__ = "execution_payment_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        ForeignKey("execution_payment_refs.id", ondelete="RESTRICT"), index=True
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("execution_invoice_refs.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    normalized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    conversion_ref: Mapped[str | None] = mapped_column(String(240))
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionSignalRow(Base):
    __tablename__ = "execution_collection_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_key: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    total_invoiced: Mapped[Decimal] = mapped_column(MONEY)
    total_allocated: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    payment_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    invoice_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    publish_error: Mapped[str | None] = mapped_column(Text)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityCaseRow(Base):
    __tablename__ = "execution_quality_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    batch_ref: Mapped[str] = mapped_column(String(200), index=True)
    supplier_ref: Mapped[str] = mapped_column(String(200), index=True)
    buyer_ref: Mapped[str] = mapped_column(String(200), index=True)
    case_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    reported_by: Mapped[str] = mapped_column(String(160))
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    currency: Mapped[str] = mapped_column(String(3))
    reserve_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    final_loss: Mapped[Decimal] = mapped_column(MONEY, default=0)
    conclusion: Mapped[str | None] = mapped_column(Text)
    independent_reviewer: Mapped[str | None] = mapped_column(String(160))
    close_evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualityCaseEventRow(Base):
    __tablename__ = "execution_quality_case_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("execution_quality_cases.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityReserveRow(Base):
    __tablename__ = "execution_quality_reserves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("execution_quality_cases.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActualCostEntryRow(Base):
    __tablename__ = "execution_actual_cost_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[str] = mapped_column(String(60), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    normalized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    normalized_currency: Mapped[str | None] = mapped_column(String(3))
    conversion_ref: Mapped[str | None] = mapped_column(String(240))
    source_reference: Mapped[str] = mapped_column(String(240), index=True)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON)
    erp_gl_ref: Mapped[str] = mapped_column(String(240), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContributionPnlSnapshotRow(Base):
    __tablename__ = "execution_contribution_pnl_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    revenue: Mapped[Decimal] = mapped_column(MONEY, default=0)
    procurement: Mapped[Decimal] = mapped_column(MONEY, default=0)
    logistics: Mapped[Decimal] = mapped_column(MONEY, default=0)
    financing: Mapped[Decimal] = mapped_column(MONEY, default=0)
    fx: Mapped[Decimal] = mapped_column(MONEY, default=0)
    commission: Mapped[Decimal] = mapped_column(MONEY, default=0)
    warranty: Mapped[Decimal] = mapped_column(MONEY, default=0)
    claims_refunds: Mapped[Decimal] = mapped_column(MONEY, default=0)
    contribution: Mapped[Decimal] = mapped_column(MONEY, default=0)
    erp_ledger_total: Mapped[Decimal] = mapped_column(MONEY)
    erp_ledger_ref: Mapped[str] = mapped_column(String(240), index=True)
    reconciliation_difference: Mapped[Decimal] = mapped_column(MONEY)
    reconciliation_status: Mapped[str] = mapped_column(String(30), index=True)
    source_refs_json: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


ReceivableRefRow = ReceivablePayableRow
PayableRefRow = ReceivablePayableRow

__all__ = [name for name in globals() if name.endswith("Row")]
