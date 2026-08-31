"""Versioned contracts for board-nine settlement facts.

The contracts intentionally contain references, rather than copies of order,
route, ERP or master-data records.  A settlement adapter may therefore be
replaced without changing the execution ledger.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettlementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettlementView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Money(SettlementModel):
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def normalize_currency(self):
        self.currency = self.currency.strip().upper()
        if not self.currency.isalpha():
            raise ValueError("currency must be an ISO alphabetic code")
        return self


class InvoiceKind(StrEnum):
    SALES = "sales"
    PURCHASE = "purchase"


class InvoiceStatus(StrEnum):
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class InvoiceRefCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    order_id: str = Field(min_length=1, max_length=160)
    invoice_kind: InvoiceKind
    invoice_ref: str = Field(min_length=1, max_length=240)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    invoice_date: date
    due_date: date | None = None
    buyer_ref: str | None = None
    supplier_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_system: str = Field(default="erpnext", max_length=80)
    normalized_amount: Decimal | None = Field(default=None, gt=0)
    normalized_currency: str | None = Field(default=None, min_length=3, max_length=3)
    conversion_ref: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_invoice(self):
        self.currency = self.currency.strip().upper()
        if self.normalized_currency:
            self.normalized_currency = self.normalized_currency.strip().upper()
        if self.due_date and self.due_date < self.invoice_date:
            raise ValueError("due_date cannot precede invoice_date")
        if self.normalized_currency and self.normalized_currency != self.currency:
            if self.normalized_amount is None or not self.conversion_ref:
                raise ValueError(
                    "cross-currency invoice normalization needs amount and conversion_ref"
                )
        elif self.normalized_amount is not None and self.normalized_currency is None:
            raise ValueError("normalized_currency is required with normalized_amount")
        return self


class InvoiceRefView(SettlementView):
    id: str
    order_id: str
    invoice_kind: str
    invoice_ref: str
    amount: Decimal
    currency: str
    normalized_amount: Decimal | None
    normalized_currency: str | None
    conversion_ref: str | None
    status: str


class PaymentRefCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    order_id: str = Field(min_length=1, max_length=160)
    payment_ref: str = Field(min_length=1, max_length=240)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    paid_at: datetime
    payer_ref: str | None = None
    bank_ref: str | None = None
    fee_amount: Decimal = Field(default=Decimal("0"), ge=0)
    fee_currency: str | None = None
    fx_difference: Decimal = Decimal("0")
    evidence_refs: list[str] = Field(default_factory=list)
    source_system: str = Field(default="erpnext", max_length=80)
    normalized_amount: Decimal | None = Field(default=None, gt=0)
    normalized_currency: str | None = Field(default=None, min_length=3, max_length=3)
    conversion_ref: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_payment(self):
        self.currency = self.currency.strip().upper()
        if self.fee_currency:
            self.fee_currency = self.fee_currency.strip().upper()
        if self.normalized_currency:
            self.normalized_currency = self.normalized_currency.strip().upper()
        if self.normalized_currency and self.normalized_currency != self.currency:
            if self.normalized_amount is None or not self.conversion_ref:
                raise ValueError(
                    "cross-currency payment normalization needs amount and conversion_ref"
                )
        if self.fee_amount and not self.fee_currency:
            self.fee_currency = self.currency
        return self


class PaymentAllocationCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    payment_id: str
    invoice_id: str
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    conversion_ref: str | None = None
    normalized_amount: Decimal | None = Field(default=None, gt=0)
    evidence_refs: list[str] = Field(default_factory=list)


class BankReconciliation(SettlementModel):
    payment_id: str
    reconciliation_ref: str = Field(min_length=1, max_length=240)
    evidence_refs: list[str] = Field(min_length=1)
    reconciled_at: datetime | None = None


class CollectionSignalView(SettlementView):
    id: str
    order_id: str
    signal_key: str
    status: str
    total_invoiced: Decimal
    total_allocated: Decimal


class QualityCaseCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    order_id: str
    batch_ref: str
    supplier_ref: str
    buyer_ref: str
    case_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1)
    reported_by: str = Field(min_length=1, max_length=160)
    evidence_refs: list[str] = Field(min_length=1)
    reserve_amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(min_length=3, max_length=3)


class QualityEventCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    case_id: str
    event_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None


class QualityClose(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    case_id: str
    conclusion: str = Field(min_length=1)
    independent_reviewer: str = Field(min_length=1, max_length=160)
    evidence_refs: list[str] = Field(min_length=1)
    final_loss: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str | None = None


class ActualCostCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    order_id: str
    category: str = Field(min_length=1, max_length=60)
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    source_reference: str = Field(min_length=1, max_length=240)
    evidence_refs: list[str] = Field(min_length=1)
    erp_gl_ref: str = Field(min_length=1, max_length=240)
    normalized_amount: Decimal | None = None
    normalized_currency: str | None = None
    conversion_ref: str | None = None


class PnlSnapshotCreate(SettlementModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    order_id: str
    currency: str = Field(min_length=3, max_length=3)
    erp_ledger_total: Decimal
    erp_ledger_ref: str = Field(min_length=1, max_length=240)
    evidence_refs: list[str] = Field(min_length=1)
    as_of: datetime


class SettlementSignal(SettlementModel):
    signal_type: str = "payment.collected.v1"
    order_id: str
    signal_key: str
    total_invoiced: Decimal
    total_allocated: Decimal
    currency: str
    payment_ids: list[str]
    invoice_ids: list[str]
    evidence_refs: list[str]
    emitted_at: datetime


class PnlTotals(SettlementModel):
    revenue: Decimal = Decimal("0")
    procurement: Decimal = Decimal("0")
    logistics: Decimal = Decimal("0")
    financing: Decimal = Decimal("0")
    fx: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    warranty: Decimal = Decimal("0")
    claims_refunds: Decimal = Decimal("0")

    @property
    def contribution(self) -> Decimal:
        return self.revenue - sum(
            (
                self.procurement,
                self.logistics,
                self.financing,
                self.fx,
                self.commission,
                self.warranty,
                self.claims_refunds,
            ),
            Decimal("0"),
        )


InvoiceCreate = InvoiceRefCreate
PaymentCreate = PaymentRefCreate
PaymentAllocation = PaymentAllocationCreate
QualityCase = QualityCaseCreate
QualityEvent = QualityEventCreate
CaseClose = QualityClose
ActualCost = ActualCostCreate
ContributionPnlSnapshot = PnlSnapshotCreate

__all__ = [name for name in globals() if not name.startswith("_")]
