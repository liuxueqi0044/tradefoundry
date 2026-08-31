"""Invoice, receivable, payment and collection services (S9.6/S9.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import aware, idempotent_row, money, new_id, request_fingerprint
from tradefoundry.execution.contracts_settlement import (
    BankReconciliation,
    InvoiceRefCreate,
    PaymentAllocationCreate,
    PaymentRefCreate,
    SettlementSignal,
)
from tradefoundry.execution.models_settlement import (
    CollectionSignalRow,
    InvoiceRefRow,
    PaymentAllocationRow,
    PaymentRefRow,
    ReceivablePayableRow,
    SettlementDiscrepancyRow,
)


class NormalizedMoney:
    def __init__(self, amount: Decimal, currency: str, conversion_ref: str | None = None):
        self.amount = money(amount)
        self.currency = currency.strip().upper()
        self.conversion_ref = conversion_ref


@runtime_checkable
class MoneyNormalizationPort(Protocol):
    """Board-eight MoneyService adapter.

    Implementations must use the supplied conversion reference (FX quote or
    conversion id) and return a deterministic amount/currency pair.  A bare
    rate or an unreferenced conversion is deliberately not part of this API.
    """

    def normalize(
        self, amount: Decimal, source_currency: str, target_currency: str, conversion_ref: str
    ) -> NormalizedMoney: ...


@runtime_checkable
class CollectionPublisherPort(Protocol):
    """Board-five Route signal boundary; implementations must not mutate routes here."""

    def publish(self, signal: SettlementSignal) -> object: ...


def _normalizer_result(result, conversion_ref: str | None) -> NormalizedMoney:
    if isinstance(result, NormalizedMoney):
        return result
    if isinstance(result, dict):
        return NormalizedMoney(
            Decimal(str(result["amount"])),
            result["currency"],
            result.get("conversion_ref", conversion_ref),
        )
    if isinstance(result, tuple) and len(result) >= 2:
        return NormalizedMoney(Decimal(str(result[0])), str(result[1]), conversion_ref)
    return NormalizedMoney(result.amount, result.currency, conversion_ref)


class InvoiceSettlementService:
    def __init__(self, session: Session, normalizer: MoneyNormalizationPort | None = None):
        self.session = session
        self.normalizer = normalizer

    def _normalize(
        self,
        amount: Decimal,
        currency: str,
        target_currency: str | None,
        conversion_ref: str | None,
        explicit_amount: Decimal | None = None,
    ) -> NormalizedMoney:
        source = currency.upper()
        target = (target_currency or source).upper()
        if source == target:
            if conversion_ref:
                raise ValueError(
                    "same-currency normalization must not carry a conversion reference"
                )
            if explicit_amount is not None and money(explicit_amount) != money(amount):
                raise ValueError("same-currency normalized amount must equal source amount")
            return NormalizedMoney(
                explicit_amount if explicit_amount is not None else amount, target
            )
        if self.normalizer is None or not conversion_ref:
            raise ValueError(
                "cross-currency amount requires MoneyNormalizationPort and conversion reference"
            )
        normalized = _normalizer_result(
            self.normalizer.normalize(amount, source, target, conversion_ref), conversion_ref
        )
        if normalized.currency != target or normalized.conversion_ref != conversion_ref:
            raise ValueError("MoneyNormalizationPort returned a mismatched conversion")
        if explicit_amount is not None and money(explicit_amount) != normalized.amount:
            raise ValueError("caller amount differs from the frozen Board 8 conversion")
        return normalized

    @staticmethod
    def _require_order(session: Session, order_id: str) -> None:
        try:
            from tradefoundry.execution.models_orders import OrderCommandRow
        except ImportError as exc:
            raise RuntimeError("execution order model is required for settlement") from exc
        if session.get(OrderCommandRow, order_id) is None:
            raise LookupError(f"order {order_id} was not found")

    def record_invoice(
        self,
        request: InvoiceRefCreate,
        *,
        target_currency: str | None = None,
        commit: bool = True,
    ) -> InvoiceRefRow:
        request_hash = request_fingerprint({"operation": "execution.invoice.record"}, request)
        existing = idempotent_row(
            self.session, InvoiceRefRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        self._require_order(self.session, request.order_id)
        normalized = self._normalize(
            request.amount,
            request.currency,
            request.normalized_currency or target_currency,
            request.conversion_ref,
            request.normalized_amount,
        )
        row = InvoiceRefRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            order_id=request.order_id,
            invoice_kind=request.invoice_kind.value,
            invoice_ref=request.invoice_ref,
            amount=money(request.amount),
            currency=request.currency,
            invoice_date=request.invoice_date,
            due_date=request.due_date,
            buyer_ref=request.buyer_ref,
            supplier_ref=request.supplier_ref,
            evidence_refs_json=request.evidence_refs,
            source_system=request.source_system,
            normalized_amount=normalized.amount,
            normalized_currency=normalized.currency,
            conversion_ref=normalized.conversion_ref,
            status="issued",
        )
        self.session.add(row)
        self.session.flush()
        self.session.add(
            ReceivablePayableRow(
                id=new_id(),
                invoice_id=row.id,
                order_id=row.order_id,
                account_kind="receivable" if row.invoice_kind == "sales" else "payable",
                original_amount=row.amount,
                original_currency=row.currency,
                outstanding_amount=row.amount,
                normalized_amount=row.normalized_amount,
                normalized_currency=row.normalized_currency,
                conversion_ref=row.conversion_ref,
            )
        )
        if commit:
            self.session.commit()
        return row

    create_invoice = record_invoice

    def reconcile_order(
        self, order_id: str, order_amount: Decimal, order_currency: str, *, commit: bool = True
    ) -> dict:
        invoices = list(
            self.session.scalars(
                select(InvoiceRefRow).where(
                    InvoiceRefRow.order_id == order_id,
                    InvoiceRefRow.invoice_kind == "sales",
                    InvoiceRefRow.status != "void",
                )
            )
        )
        expected = money(order_amount)
        amounts: list[Decimal] = []
        for invoice in invoices:
            normalized = self._normalize(
                invoice.amount,
                invoice.currency,
                order_currency,
                invoice.conversion_ref,
                invoice.normalized_amount
                if invoice.normalized_currency == order_currency
                else None,
            )
            amounts.append(normalized.amount)
        actual = money(sum(amounts, Decimal("0")))
        difference = money(actual - expected)
        result = {
            "order_id": order_id,
            "expected": expected,
            "actual": actual,
            "difference": difference,
            "currency": order_currency.upper(),
            "reconciled": difference == 0,
            "invoice_ids": [row.id for row in invoices],
        }
        if difference:
            self.session.add(
                SettlementDiscrepancyRow(
                    id=new_id(),
                    order_id=order_id,
                    subject_type="invoice_set",
                    subject_id=order_id,
                    expected_amount=expected,
                    actual_amount=actual,
                    currency=order_currency.upper(),
                    difference=difference,
                    reason="sales invoice total differs from order amount",
                    explanation_json={
                        "invoice_ids": result["invoice_ids"],
                        "target_currency": order_currency.upper(),
                    },
                )
            )
        if commit:
            self.session.commit()
        return result


class PaymentSettlementService:
    def __init__(
        self,
        session: Session,
        normalizer: MoneyNormalizationPort | None = None,
        publisher: CollectionPublisherPort | None = None,
    ):
        self.session = session
        self.normalizer = normalizer
        self.publisher = publisher

    def record_payment(
        self, request: PaymentRefCreate, *, target_currency: str | None = None
    ) -> PaymentRefRow:
        request_hash = request_fingerprint({"operation": "execution.payment.record"}, request)
        existing = idempotent_row(
            self.session, PaymentRefRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        InvoiceSettlementService._require_order(self.session, request.order_id)
        target = (request.normalized_currency or target_currency or request.currency).upper()
        if target != request.currency.upper():
            if self.normalizer is None or not request.conversion_ref:
                raise ValueError(
                    "cross-currency payment requires MoneyNormalizationPort and "
                    "conversion reference"
                )
            normalized = _normalizer_result(
                self.normalizer.normalize(
                    request.amount, request.currency, target, request.conversion_ref
                ),
                request.conversion_ref,
            )
            if (
                normalized.currency != target
                or normalized.conversion_ref != request.conversion_ref
                or request.normalized_amount is not None
                and money(request.normalized_amount) != normalized.amount
            ):
                raise ValueError("payment differs from the frozen Board 8 conversion")
        else:
            if request.normalized_amount is not None and money(request.normalized_amount) != money(
                request.amount
            ):
                raise ValueError("same-currency normalized amount must equal source amount")
            normalized = NormalizedMoney(request.normalized_amount or request.amount, target)
        fee_currency = (request.fee_currency or request.currency).upper()
        if request.fee_amount and fee_currency != normalized.currency:
            raise ValueError(
                "cross-currency bank fees must be recorded as a Board 8-normalized actual cost"
            )
        row = PaymentRefRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            order_id=request.order_id,
            payment_ref=request.payment_ref,
            amount=money(request.amount),
            currency=request.currency,
            paid_at=aware(request.paid_at),
            payer_ref=request.payer_ref,
            bank_ref=request.bank_ref,
            fee_amount=money(request.fee_amount),
            fee_currency=fee_currency,
            fx_difference=money(request.fx_difference),
            evidence_refs_json=request.evidence_refs,
            source_system=request.source_system,
            normalized_amount=normalized.amount,
            normalized_currency=normalized.currency,
            conversion_ref=normalized.conversion_ref,
            status="unallocated",
        )
        self.session.add(row)
        self.session.commit()
        return row

    create_payment = record_payment

    def allocate(self, request: PaymentAllocationCreate) -> PaymentAllocationRow:
        request_hash = request_fingerprint({"operation": "execution.payment.allocate"}, request)
        existing = idempotent_row(
            self.session, PaymentAllocationRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        payment = self.session.get(PaymentRefRow, request.payment_id)
        invoice = self.session.get(InvoiceRefRow, request.invoice_id)
        if payment is None or invoice is None:
            raise LookupError("payment and invoice are required for allocation")
        if payment.order_id != invoice.order_id:
            raise ValueError("payment and invoice belong to different orders")
        if request.currency.upper() != invoice.currency.upper():
            raise ValueError("allocation amount must be expressed in the invoice currency")
        target = (invoice.normalized_currency or invoice.currency).upper()
        if payment.normalized_currency != target:
            raise ValueError("payment and invoice must share one normalized allocation currency")
        if target != request.currency.upper():
            if self.normalizer is None or not request.conversion_ref:
                raise ValueError(
                    "cross-currency allocation needs MoneyNormalizationPort and "
                    "conversion reference"
                )
            normalized_amount = _normalizer_result(
                self.normalizer.normalize(
                    request.amount, request.currency, target, request.conversion_ref
                ),
                request.conversion_ref,
            ).amount
            if (
                request.normalized_amount is not None
                and money(request.normalized_amount) != money(normalized_amount)
            ):
                raise ValueError("allocation differs from the frozen Board 8 conversion")
        else:
            if request.normalized_amount is not None and money(request.normalized_amount) != money(
                request.amount
            ):
                raise ValueError("same-currency allocation normalized amount must equal amount")
            normalized_amount = request.amount
        prior_allocated = self.session.scalar(
            select(func.coalesce(func.sum(PaymentAllocationRow.normalized_amount), 0)).where(
                PaymentAllocationRow.payment_id == payment.id
            )
        ) or Decimal("0")
        if money(prior_allocated + normalized_amount) > money(payment.normalized_amount):
            raise ValueError("allocation exceeds the normalized payment amount")
        row = PaymentAllocationRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            payment_id=payment.id,
            invoice_id=invoice.id,
            amount=money(request.amount),
            currency=request.currency.upper(),
            normalized_amount=money(normalized_amount),
            conversion_ref=request.conversion_ref,
            evidence_refs_json=request.evidence_refs,
        )
        self.session.add(row)
        self.session.flush()
        allocated_normalized = self.session.scalar(
            select(func.coalesce(func.sum(PaymentAllocationRow.normalized_amount), 0)).where(
                PaymentAllocationRow.payment_id == payment.id
            )
        ) or Decimal("0")
        if payment.normalized_currency == target:
            payment.status = (
                "allocated"
                if allocated_normalized >= payment.normalized_amount
                else "partially_allocated"
            )
        else:
            # Do not compare raw amounts across currencies.  A payment with a
            # different target currency remains reviewable until Board 8
            # supplies the second conversion.
            payment.status = "partially_allocated"
        if invoice.status != "void":
            inv_total = self.session.scalar(
                select(func.coalesce(func.sum(PaymentAllocationRow.amount), 0)).where(
                    PaymentAllocationRow.invoice_id == invoice.id
                )
            ) or Decimal("0")
            invoice.status = "paid" if inv_total >= invoice.amount else "partially_paid"
        self.session.commit()
        return row

    allocate_payment = allocate

    def reconcile_bank(self, reconciliation: BankReconciliation) -> PaymentRefRow:
        payment = self.session.get(PaymentRefRow, reconciliation.payment_id)
        if payment is None:
            raise LookupError(f"payment {reconciliation.payment_id} was not found")
        if not payment.bank_ref:
            raise ValueError("bank reconciliation requires the originating bank reference")
        if payment.bank_reconciled:
            if (
                payment.bank_reconciliation_ref == reconciliation.reconciliation_ref
                and payment.bank_reconciliation_evidence_json == list(reconciliation.evidence_refs)
            ):
                return payment
            raise ValueError("bank reconciliation facts are immutable")
        payment.bank_reconciliation_ref = reconciliation.reconciliation_ref
        payment.bank_reconciliation_evidence_json = list(reconciliation.evidence_refs)
        payment.bank_reconciled = True
        from datetime import UTC, datetime

        payment.reconciled_at = reconciliation.reconciled_at or datetime.now(UTC)
        payment.status = "bank_reconciled"
        self.session.commit()
        return payment

    def emit_collection_signal(
        self, order_id: str, *, currency: str | None = None
    ) -> CollectionSignalRow | None:
        invoices = list(
            self.session.scalars(
                select(InvoiceRefRow).where(
                    InvoiceRefRow.order_id == order_id,
                    InvoiceRefRow.invoice_kind == "sales",
                    InvoiceRefRow.status != "void",
                )
            )
        )
        if not invoices:
            return None
        allocated_by_invoice = {
            invoice.id: (
                self.session.scalar(
                    select(
                        func.coalesce(func.sum(PaymentAllocationRow.normalized_amount), 0)
                    ).where(PaymentAllocationRow.invoice_id == invoice.id)
                )
                or Decimal("0")
            )
            for invoice in invoices
        }
        target = (currency or invoices[0].normalized_currency or invoices[0].currency).upper()
        if any(
            (invoice.normalized_currency or invoice.currency).upper() != target
            for invoice in invoices
        ):
            raise ValueError("all collection invoices must share one normalized currency")
        expected = money(sum((invoice.normalized_amount or invoice.amount) for invoice in invoices))
        actual = money(sum(allocated_by_invoice.values()))
        if any(
            value < (invoice.normalized_amount or invoice.amount)
            for invoice, value in zip(invoices, allocated_by_invoice.values(), strict=True)
        ):
            return None
        signal_key = f"collection:{order_id}"
        existing = self.session.scalar(
            select(CollectionSignalRow).where(CollectionSignalRow.signal_key == signal_key)
        )
        if existing is not None and existing.status == "published":
            return existing
        allocation_rows = list(
            self.session.scalars(
                select(PaymentAllocationRow).where(
                    PaymentAllocationRow.invoice_id.in_([invoice.id for invoice in invoices])
                )
            )
        )
        payment_ids = sorted({row.payment_id for row in allocation_rows})
        payment_rows = [self.session.get(PaymentRefRow, payment_id) for payment_id in payment_ids]
        payment_rows = [payment for payment in payment_rows if payment is not None]
        if not payment_rows or any(not payment.bank_reconciled for payment in payment_rows):
            return None
        evidence = sorted({ref for invoice in invoices for ref in invoice.evidence_refs_json})
        evidence = sorted(
            set(evidence).union(
                *(
                    set(payment.evidence_refs_json).union(payment.bank_reconciliation_evidence_json)
                    for payment in payment_rows
                )
            )
        )
        evidence = sorted(
            set(evidence).union(*(set(row.evidence_refs_json) for row in allocation_rows))
        )
        signal = SettlementSignal(
            order_id=order_id,
            signal_key=signal_key,
            total_invoiced=expected,
            total_allocated=actual,
            currency=target,
            payment_ids=payment_ids,
            invoice_ids=[invoice.id for invoice in invoices],
            evidence_refs=evidence,
            emitted_at=datetime.now(UTC),
        )
        row = existing or CollectionSignalRow(
            id=new_id(),
            signal_key=signal_key,
            order_id=order_id,
            total_invoiced=expected,
            total_allocated=actual,
            currency=target,
            payment_ids_json=payment_ids,
            invoice_ids_json=signal.invoice_ids,
            evidence_refs_json=evidence,
            status="pending",
        )
        if existing is None:
            self.session.add(row)
        self.session.commit()  # durable pending signal survives publisher failure
        if self.publisher is None:
            raise RuntimeError("CollectionPublisherPort is required to emit collected signals")
        row.publish_attempts += 1
        try:
            self.publisher.publish(signal)
        except Exception as exc:
            row.status = "retry"
            row.publish_error = str(exc)
            self.session.commit()
            raise
        row.status = "published"
        row.publish_error = None
        row.published_at = datetime.now(UTC)
        self.session.commit()
        return row

    publish_collected = emit_collection_signal


InvoiceService = InvoiceSettlementService
PaymentService = PaymentSettlementService

__all__ = [
    "CollectionPublisherPort",
    "InvoiceService",
    "InvoiceSettlementService",
    "MoneyNormalizationPort",
    "NormalizedMoney",
    "PaymentService",
    "PaymentSettlementService",
]
