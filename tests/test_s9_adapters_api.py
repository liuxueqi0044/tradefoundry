from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradefoundry.api import app
from tradefoundry.controltower.models import MoneyConversionRow
from tradefoundry.deals.models import DealRouteRow, ObservationRow
from tradefoundry.execution.adapters import (
    Board8MoneyNormalizationAdapter,
    DealsCollectionPublisher,
)
from tradefoundry.execution.contracts_settlement import SettlementSignal
from tradefoundry.execution.models_orders import OrderCommandRow


def test_board8_money_adapter_accepts_only_exact_frozen_conversion(session):
    session.add(
        MoneyConversionRow(
            id="conversion-1",
            idempotency_key="conversion-adapter-1",
            request_hash="a" * 64,
            source_amount=Decimal("100"),
            source_currency="EUR",
            target_amount=Decimal("110"),
            target_currency="USD",
            applied_rate=Decimal("1.10"),
            converted_at=datetime(2026, 8, 30, tzinfo=UTC),
            source_snapshot_json={"fx_quote_id": "quote-1"},
        )
    )
    session.commit()
    adapter = Board8MoneyNormalizationAdapter(session)
    normalized = adapter.normalize(Decimal("100"), "EUR", "USD", "conversion-1")
    assert normalized.amount == Decimal("110.0000")
    with pytest.raises(ValueError, match="exact amount"):
        adapter.normalize(Decimal("101"), "EUR", "USD", "conversion-1")


def test_collection_adapter_uses_board5_gate_and_is_idempotent(session, deal_route_factory):
    _, route = deal_route_factory()
    route = session.get(DealRouteRow, route.id)
    route.stage = "committed"
    order = OrderCommandRow(
        id="adapter-order",
        order_key="adapter-order",
        idempotency_key="adapter-order-command",
        request_hash="b" * 64,
        route_id=route.id,
        order_kind="sales",
        customer_entity_id="buyer-1",
        item_ref="item-1",
        quantity=Decimal("1"),
        quantity_unit="each",
        unit_price=Decimal("100"),
        currency="USD",
        terms_json={},
        commitment_claim_id="claim-1",
        commitment_evidence_ids_json=["fragment-1"],
        policy_decision_id="policy-1",
        approval_request_id="approval-1",
        token_id="token-1",
        params_hash="c" * 64,
        requested_by="operator",
        status="succeeded",
    )
    session.add(order)
    session.commit()
    signal = SettlementSignal(
        order_id=order.id,
        signal_key=f"collection:{order.id}",
        total_invoiced=Decimal("100"),
        total_allocated=Decimal("100"),
        currency="USD",
        payment_ids=["payment-1"],
        invoice_ids=["invoice-1"],
        evidence_refs=["bank-reconciliation-1"],
        emitted_at=datetime.now(UTC),
    )
    publisher = DealsCollectionPublisher(session)
    publisher.publish(signal)
    publisher.publish(signal)
    session.refresh(route)
    assert route.stage == "collected"
    observations = session.query(ObservationRow).filter_by(route_id=route.id).all()
    assert [row.observation_type for row in observations] == ["payment_reconciled"]


def test_openapi_exposes_all_board9_resource_families():
    paths = app.openapi()["paths"]
    expected = {
        "/v1/execution/erp/resources",
        "/v1/execution/erp/order-events",
        "/v1/execution/orders",
        "/v1/execution/milestones",
        "/v1/execution/shipment-documents",
        "/v1/execution/invoices",
        "/v1/execution/payments",
        "/v1/execution/payment-allocations",
        "/v1/execution/bank-reconciliations",
        "/v1/execution/quality-cases",
        "/v1/execution/actual-costs",
        "/v1/execution/pnl-snapshots",
        "/v1/execution/outcomes",
        "/v1/execution/prediction-actuals",
        "/v1/execution/learning-datasets",
        "/v1/execution/evaluations",
        "/v1/execution/review-proposals",
        "/v1/execution/dashboard-snapshots",
    }
    assert expected <= set(paths)
