"""Realized contribution P&L attribution (S9.9)."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import idempotent_row, money, new_id, request_fingerprint
from tradefoundry.execution.contracts_settlement import ActualCostCreate, PnlSnapshotCreate
from tradefoundry.execution.models_settlement import (
    ActualCostEntryRow,
    ContributionPnlSnapshotRow,
    InvoiceRefRow,
    PaymentRefRow,
    QualityCaseRow,
)
from tradefoundry.execution.settlement import (
    InvoiceSettlementService,
    MoneyNormalizationPort,
    NormalizedMoney,
    _normalizer_result,
)

_CATEGORIES = (
    "procurement",
    "logistics",
    "financing",
    "fx",
    "commission",
    "warranty",
    "claims_refunds",
)
_CATEGORY_ALIASES = {
    "purchase": "procurement",
    "purchases": "procurement",
    "freight": "logistics",
    "shipping": "logistics",
    "bank_fee": "financing",
    "fees": "financing",
    "claim": "claims_refunds",
    "refund": "claims_refunds",
    "quality": "warranty",
}


class PnlService:
    def __init__(self, session: Session, normalizer: MoneyNormalizationPort | None = None):
        self.session = session
        self.normalizer = normalizer

    def record_actual_cost(
        self, request: ActualCostCreate, *, target_currency: str | None = None
    ) -> ActualCostEntryRow:
        request_hash = request_fingerprint({"operation": "execution.actual_cost.record"}, request)
        existing = idempotent_row(
            self.session, ActualCostEntryRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        InvoiceSettlementService._require_order(self.session, request.order_id)
        target = (request.normalized_currency or target_currency or request.currency).upper()
        if target != request.currency.upper():
            if not request.conversion_ref:
                raise ValueError("cross-currency cost needs a conversion reference")
            if self.normalizer is not None:
                normalized = _normalizer_result(
                    self.normalizer.normalize(
                        request.amount, request.currency, target, request.conversion_ref
                    ),
                    request.conversion_ref,
                )
            else:
                raise ValueError(
                    "cross-currency cost requires MoneyNormalizationPort and conversion reference"
                )
        else:
            if request.normalized_amount is not None and money(request.normalized_amount) != money(
                request.amount
            ):
                raise ValueError("same-currency normalized amount must equal source amount")
            normalized = NormalizedMoney(request.normalized_amount or request.amount, target)
        row = ActualCostEntryRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            order_id=request.order_id,
            category=request.category.strip().lower(),
            amount=money(request.amount),
            currency=request.currency.upper(),
            normalized_amount=normalized.amount,
            normalized_currency=normalized.currency,
            conversion_ref=normalized.conversion_ref,
            source_reference=request.source_reference,
            evidence_refs_json=list(request.evidence_refs),
            erp_gl_ref=request.erp_gl_ref,
        )
        self.session.add(row)
        self.session.commit()
        return row

    create_actual_cost = record_actual_cost

    @staticmethod
    def _sum(rows: Iterable, field: str = "normalized_amount") -> Decimal:
        return money(sum((getattr(row, field) or Decimal("0") for row in rows), Decimal("0")))

    def snapshot(self, request: PnlSnapshotCreate) -> ContributionPnlSnapshotRow:
        request_hash = request_fingerprint({"operation": "execution.pnl.snapshot"}, request)
        existing = idempotent_row(
            self.session, ContributionPnlSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        InvoiceSettlementService._require_order(self.session, request.order_id)
        target = request.currency.upper()
        invoices = list(
            self.session.scalars(
                select(InvoiceRefRow).where(
                    InvoiceRefRow.order_id == request.order_id, InvoiceRefRow.status != "void"
                )
            )
        )
        sales = [row for row in invoices if row.invoice_kind == "sales"]
        purchases = [row for row in invoices if row.invoice_kind == "purchase"]
        if not sales:
            raise ValueError("realized PnL requires at least one sales invoice")
        # Invoices are normalized at intake. Refuse to silently mix currencies.
        all_rows = sales + purchases
        if any((row.normalized_currency or row.currency).upper() != target for row in all_rows):
            raise ValueError("all invoice amounts must be normalized to the P&L currency")
        revenue = self._sum(sales)
        procurement = self._sum(purchases)
        costs = list(
            self.session.scalars(
                select(ActualCostEntryRow).where(ActualCostEntryRow.order_id == request.order_id)
            )
        )
        if any((row.normalized_currency or row.currency).upper() != target for row in costs):
            raise ValueError("all actual costs must be normalized to the P&L currency")
        totals = {name: Decimal("0") for name in _CATEGORIES}
        source_refs: dict[str, list[str]] = {name: [] for name in ("revenue", *_CATEGORIES)}
        evidence = set(request.evidence_refs)
        source_refs["revenue"] = [row.id for row in sales]
        source_refs["procurement"] = [row.id for row in purchases]
        for row in sales + purchases:
            evidence.update(row.evidence_refs_json)
        for row in costs:
            category = _CATEGORY_ALIASES.get(row.category, row.category)
            if category not in totals:
                raise ValueError(f"unsupported realized cost category: {row.category}")
            totals[category] += row.normalized_amount or Decimal("0")
            source_refs[category].append(row.id)
            evidence.update(row.evidence_refs_json)
        # Bank/ERP payment charges and realized FX are facts, not optional
        # hand-entered costs.  Include them once in the P&L snapshot.
        payments = list(
            self.session.scalars(
                select(PaymentRefRow).where(PaymentRefRow.order_id == request.order_id)
            )
        )
        for payment in payments:
            if payment.fee_currency.upper() != target or payment.currency.upper() != target:
                raise ValueError("payment fee/FX currency must be normalized to the P&L currency")
            totals["financing"] += payment.fee_amount
            totals["fx"] += payment.fx_difference
            source_refs["financing"].append(payment.id)
            source_refs["fx"].append(payment.id)
            evidence.update(payment.evidence_refs_json)
        cases = list(
            self.session.scalars(
                select(QualityCaseRow).where(
                    QualityCaseRow.order_id == request.order_id, QualityCaseRow.status == "closed"
                )
            )
        )
        for case in cases:
            if case.currency.upper() != target:
                raise ValueError("quality final loss is not normalized to the P&L currency")
            totals["claims_refunds"] += case.final_loss
            source_refs["claims_refunds"].append(case.id)
            evidence.update(case.close_evidence_refs_json)
        totals["procurement"] += procurement
        contribution = money(revenue - sum(totals.values(), Decimal("0")))
        ledger_total = money(request.erp_ledger_total)
        difference = money(contribution - ledger_total)
        row = ContributionPnlSnapshotRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            order_id=request.order_id,
            as_of=request.as_of,
            currency=target,
            revenue=revenue,
            procurement=money(procurement),
            logistics=money(totals["logistics"]),
            financing=money(totals["financing"]),
            fx=money(totals["fx"]),
            commission=money(totals["commission"]),
            warranty=money(totals["warranty"]),
            claims_refunds=money(totals["claims_refunds"]),
            contribution=contribution,
            erp_ledger_total=ledger_total,
            erp_ledger_ref=request.erp_ledger_ref,
            reconciliation_difference=difference,
            reconciliation_status="reconciled" if difference == 0 else "review",
            source_refs_json=source_refs,
            evidence_refs_json=sorted(evidence),
        )
        self.session.add(row)
        self.session.commit()
        return row

    create_snapshot = snapshot


ContributionPnlService = PnlService

__all__ = ["ContributionPnlService", "PnlService"]
