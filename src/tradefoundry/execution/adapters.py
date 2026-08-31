"""Trusted adapters connecting Board 9 facts to Boards 5 and 8."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from tradefoundry.controltower.models import MoneyConversionRow
from tradefoundry.deals.contracts import ObservationCreate, RouteStage, StageTransitionRequest
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.deals.observations import ObservationService
from tradefoundry.deals.state_machine import RouteStageService
from tradefoundry.execution.common import money
from tradefoundry.execution.contracts_settlement import SettlementSignal
from tradefoundry.execution.models_orders import OrderCommandRow
from tradefoundry.execution.settlement import NormalizedMoney


class Board8MoneyNormalizationAdapter:
    """Resolve only a frozen Board 8 conversion; never accept a caller's rate."""

    def __init__(self, session: Session):
        self.session = session

    def normalize(
        self,
        amount: Decimal,
        source_currency: str,
        target_currency: str,
        conversion_ref: str,
    ) -> NormalizedMoney:
        row = self.session.get(MoneyConversionRow, conversion_ref)
        if row is None:
            raise LookupError(f"Board 8 money conversion {conversion_ref} was not found")
        if (
            money(row.source_amount) != money(amount)
            or row.source_currency != source_currency.upper()
            or row.target_currency != target_currency.upper()
        ):
            raise ValueError(
                "Board 8 conversion is not bound to this exact amount and currency pair"
            )
        return NormalizedMoney(row.target_amount, row.target_currency, row.id)


class DealsCollectionPublisher:
    """Publish a reconciled collection fact through the Board 5 state machine.

    The publisher never edits a DealRoute directly. A durable Board 9 signal is
    created before this adapter runs, and Board 5 independently rechecks the
    COMMITTED -> COLLECTED transition gate.
    """

    def __init__(self, session: Session, *, actor: str = "execution-settlement"):
        self.session = session
        self.actor = actor

    def publish(self, signal: SettlementSignal):
        order = self.session.get(OrderCommandRow, signal.order_id)
        if order is None:
            raise LookupError(f"order {signal.order_id} was not found")
        route = self.session.get(DealRouteRow, order.route_id)
        if route is None:
            raise LookupError(f"DealRoute {order.route_id} was not found")
        if route.stage not in {RouteStage.COMMITTED.value, RouteStage.COLLECTED.value}:
            raise ValueError("collection can only publish for a committed DealRoute")
        observation = ObservationService(self.session).record(
            route.id,
            ObservationCreate(
                idempotency_key=f"{signal.signal_key}:observation",
                observation_type="payment_reconciled",
                raw_text="ERP and bank payment allocations reconciled by Board 9.",
                structured_interpretation={
                    "signal_key": signal.signal_key,
                    "order_id": signal.order_id,
                    "total_invoiced": str(signal.total_invoiced),
                    "total_allocated": str(signal.total_allocated),
                    "currency": signal.currency,
                    "payment_ids": signal.payment_ids,
                    "invoice_ids": signal.invoice_ids,
                    "evidence_refs": signal.evidence_refs,
                },
                external_ref=signal.signal_key,
                occurred_at=signal.emitted_at,
            ),
        )
        self.session.refresh(route)
        if route.stage == RouteStage.COLLECTED.value:
            return observation
        transition = RouteStageService(self.session).transition(
            route.id,
            StageTransitionRequest(
                idempotency_key=f"{signal.signal_key}:transition:v{route.version}",
                expected_version=route.version,
                to_stage=RouteStage.COLLECTED,
                actor=self.actor,
                reason="Bank-reconciled sales invoices are fully allocated.",
            ),
        )
        if transition.outcome != "accepted":
            raise ValueError(
                "collection transition was rejected: " + "; ".join(transition.reasons_json)
            )
        return transition
