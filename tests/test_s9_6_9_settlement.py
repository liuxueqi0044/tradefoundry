from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tradefoundry.execution.contracts_settlement import (
    ActualCostCreate,
    BankReconciliation,
    InvoiceRefCreate,
    PaymentAllocationCreate,
    PaymentRefCreate,
    PnlSnapshotCreate,
    QualityCaseCreate,
    QualityClose,
    QualityEventCreate,
)
from tradefoundry.execution.models_orders import OrderCommandRow
from tradefoundry.execution.models_settlement import (
    CollectionSignalRow,
    InvoiceRefRow,
    QualityCaseEventRow,
    SettlementDiscrepancyRow,
)
from tradefoundry.execution.pnl import PnlService
from tradefoundry.execution.quality import QualityCaseService
from tradefoundry.execution.settlement import (
    InvoiceSettlementService,
    NormalizedMoney,
    PaymentSettlementService,
)


class FixtureNormalizer:
    def normalize(self, amount, source_currency, target_currency, conversion_ref):
        assert conversion_ref == "fx-1"
        factor = (
            Decimal("7.2")
            if source_currency == "EUR" and target_currency == "USD"
            else Decimal("1")
        )
        return NormalizedMoney(Decimal(amount) * factor, target_currency, conversion_ref)


class Publisher:
    def __init__(self):
        self.signals = []

    def publish(self, signal):
        self.signals.append(signal)


def make_order(session, order_id="order-1", amount="1000"):
    row = OrderCommandRow(
        id=order_id,
        order_key=order_id,
        idempotency_key=f"cmd-{order_id}",
        request_hash="h",
        route_id="route-1",
        order_kind="sales",
        customer_entity_id="buyer-1",
        supplier_entity_id=None,
        item_ref="item-1",
        quantity=Decimal("1"),
        quantity_unit="unit",
        unit_price=Decimal(amount),
        currency="USD",
        terms_json={},
        commitment_claim_id="claim-1",
        commitment_evidence_ids_json=["ev-order"],
        policy_decision_id="policy-1",
        approval_request_id="approval-1",
        token_id="token-1",
        params_hash="params",
        requested_by="tester",
        status="issued",
    )
    session.add(row)
    session.commit()
    return row


def invoice(order_id, key, kind, amount, currency="USD", **kwargs):
    return InvoiceRefCreate(
        idempotency_key=key,
        order_id=order_id,
        invoice_kind=kind,
        invoice_ref=f"inv-{key}",
        amount=Decimal(amount),
        currency=currency,
        invoice_date=date(2026, 8, 1),
        evidence_refs=[f"ev-{key}"],
        **kwargs,
    )


def test_s9_6_invoices_normalize_and_explain_discrepancy(session):
    make_order(session, amount="460")
    service = InvoiceSettlementService(session, FixtureNormalizer())
    service.record_invoice(invoice("order-1", "i-usd", "sales", "100"))
    service.record_invoice(
        invoice(
            "order-1",
            "i-eur",
            "sales",
            "50",
            "EUR",
            normalized_amount="360",
            normalized_currency="USD",
            conversion_ref="fx-1",
        )
    )
    result = service.reconcile_order("order-1", Decimal("460"), "USD")
    assert result["reconciled"] is True
    assert result["actual"] == Decimal("460.0000")
    result = service.reconcile_order("order-1", Decimal("500"), "USD")
    assert result["reconciled"] is False
    assert session.query(SettlementDiscrepancyRow).count() == 1
    with pytest.raises(ValueError, match="MoneyNormalizationPort"):
        InvoiceSettlementService(session).record_invoice(
            invoice(
                "order-1",
                "i-gbp",
                "sales",
                "10",
                "GBP",
                normalized_amount="12",
                normalized_currency="USD",
                conversion_ref="caller-claimed",
            )
        )


def test_s9_7_requires_bank_reconciliation_and_emits_once(session):
    make_order(session)
    InvoiceSettlementService(session).record_invoice(invoice("order-1", "i-1", "sales", "100"))
    publisher = Publisher()
    service = PaymentSettlementService(session, publisher=publisher)
    payment = service.record_payment(
        PaymentRefCreate(
            idempotency_key="p-1",
            order_id="order-1",
            payment_ref="bank-payment-1",
            amount=Decimal("100"),
            currency="USD",
            paid_at=datetime.now(UTC),
            bank_ref="stmt-1",
            evidence_refs=["ev-payment"],
            fee_amount=Decimal("1"),
        )
    )
    service.allocate(
        PaymentAllocationCreate(
            idempotency_key="a-1",
            payment_id=payment.id,
            invoice_id=session.query(InvoiceRefRow).one().id,
            amount=Decimal("100"),
            currency="USD",
            evidence_refs=["ev-allocation"],
        )
    )
    assert service.emit_collection_signal("order-1") is None
    service.reconcile_bank(
        BankReconciliation(
            payment_id=payment.id,
            reconciliation_ref="erp-recon-1",
            evidence_refs=["ev-bank"],
        )
    )
    signal = service.emit_collection_signal("order-1")
    assert signal is not None and signal.status == "published"
    assert publisher.signals[0].evidence_refs == [
        "ev-allocation",
        "ev-bank",
        "ev-i-1",
        "ev-payment",
    ]
    assert service.emit_collection_signal("order-1") is signal
    assert session.query(CollectionSignalRow).count() == 1


def test_s9_8_case_has_append_only_events_and_independent_close(session):
    make_order(session)
    service = QualityCaseService(session)
    case = service.open_case(
        QualityCaseCreate(
            idempotency_key="q-1",
            order_id="order-1",
            batch_ref="batch-1",
            supplier_ref="supplier-1",
            buyer_ref="buyer-1",
            case_type="defect",
            description="broken units",
            reported_by="quality-reporter",
            evidence_refs=["ev-q"],
            reserve_amount=Decimal("40"),
            currency="USD",
        )
    )
    service.append_event(
        QualityEventCreate(
            idempotency_key="qe-1",
            case_id=case.id,
            event_type="inspection",
            description="inspection found defect",
            evidence_refs=["ev-inspection"],
        )
    )
    with pytest.raises(ValueError):
        service.close_case(
            QualityClose(
                idempotency_key="qc-bad",
                case_id=case.id,
                conclusion="liable",
                independent_reviewer="",
                evidence_refs=[],
                final_loss=Decimal("30"),
                currency="USD",
            )
        )
    with pytest.raises(ValueError, match="reporter cannot independently close"):
        service.close_case(
            QualityClose(
                idempotency_key="qc-same-reporter",
                case_id=case.id,
                conclusion="supplier liable",
                independent_reviewer="quality-reporter",
                evidence_refs=["ev-final"],
                final_loss=Decimal("30"),
                currency="USD",
            )
        )
    closed = service.close_case(
        QualityClose(
            idempotency_key="qc-1",
            case_id=case.id,
            conclusion="supplier liable",
            independent_reviewer="reviewer-2",
            evidence_refs=["ev-final"],
            final_loss=Decimal("30"),
            currency="USD",
        )
    )
    assert closed.status == "closed" and closed.final_loss == Decimal("30.0000")
    assert session.query(QualityCaseEventRow).count() == 2


def test_s9_9_pnl_traces_costs_fees_losses_and_erp_review(session):
    make_order(session)
    inv_service = InvoiceSettlementService(session)
    inv_service.record_invoice(invoice("order-1", "sale", "sales", "1000"))
    inv_service.record_invoice(invoice("order-1", "purchase", "purchase", "400"))
    pnl = PnlService(session)
    pnl.record_actual_cost(
        ActualCostCreate(
            idempotency_key="cost-1",
            order_id="order-1",
            category="logistics",
            amount=Decimal("100"),
            currency="USD",
            source_reference="freight-1",
            evidence_refs=["ev-freight"],
            erp_gl_ref="GL-1",
        )
    )
    PaymentSettlementService(session).record_payment(
        PaymentRefCreate(
            idempotency_key="pnl-payment",
            order_id="order-1",
            payment_ref="bank-2",
            amount=Decimal("1"),
            currency="USD",
            paid_at=datetime.now(UTC),
            fee_amount=Decimal("10"),
            fx_difference=Decimal("5"),
            evidence_refs=["ev-fee"],
        )
    )
    quality = QualityCaseService(session)
    case = quality.open_case(
        QualityCaseCreate(
            idempotency_key="q-pnl",
            order_id="order-1",
            batch_ref="batch-1",
            supplier_ref="supplier-1",
            buyer_ref="buyer-1",
            case_type="claim",
            description="refund",
            reported_by="quality-reporter",
            evidence_refs=["ev-claim"],
            currency="USD",
        )
    )
    quality.close_case(
        QualityClose(
            idempotency_key="q-pnl-close",
            case_id=case.id,
            conclusion="refund approved",
            independent_reviewer="reviewer-2",
            evidence_refs=["ev-claim-final"],
            final_loss=Decimal("30"),
            currency="USD",
        )
    )
    snapshot = pnl.snapshot(
        PnlSnapshotCreate(
            idempotency_key="snap-1",
            order_id="order-1",
            currency="USD",
            erp_ledger_total=Decimal("455"),
            erp_ledger_ref="ERP-GL-CLOSE-1",
            evidence_refs=["ev-ledger"],
            as_of=datetime.now(UTC),
        )
    )
    assert snapshot.contribution == Decimal("455.0000")
    assert snapshot.reconciliation_status == "reconciled"
    review = pnl.snapshot(
        PnlSnapshotCreate(
            idempotency_key="snap-2",
            order_id="order-1",
            currency="USD",
            erp_ledger_total=Decimal("456"),
            erp_ledger_ref="ERP-GL-CLOSE-2",
            evidence_refs=["ev-ledger"],
            as_of=datetime.now(UTC),
        )
    )
    assert review.reconciliation_status == "review"
