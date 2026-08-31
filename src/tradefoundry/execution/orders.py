from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.deals.models import DealRouteRow
from tradefoundry.evidence.models import ClaimEvidenceRow, ClaimRow
from tradefoundry.execution.common import (
    aware,
    idempotent_row,
    new_id,
    quantity,
    request_fingerprint,
)
from tradefoundry.execution.contracts_orders import ErpOrderEvent, ErpResource, OrderCommand
from tradefoundry.execution.models_orders import (
    ErpMappingRow,
    ExecutionOutboxAttemptRow,
    ExecutionOutboxRow,
    ExecutionReviewIssueRow,
    OrderCommandRow,
    OrderSnapshotRow,
)
from tradefoundry.ingestion.hashing import payload_hash


class OrderService:
    def __init__(self, session: Session, token_guard, *, provider: str = "erpnext"):
        self.session, self.token_guard, self.provider = session, token_guard, provider

    def issue(self, command: OrderCommand) -> OrderCommandRow:
        request_hash = request_fingerprint({"operation": "execution.order.issue"}, command)
        existing = idempotent_row(
            self.session, OrderCommandRow, command.idempotency_key, request_hash
        )
        if existing:
            return existing
        self._require_commitment(command)
        route = self.session.get(DealRouteRow, command.route_id)
        if route is None:
            raise LookupError(f"DealRoute {command.route_id} was not found")
        if route.stage != "committed":
            raise ValueError("orders can only be issued for a committed DealRoute")
        party_mapping, item_mapping = self._require_erp_mappings(command)
        # No raw token ever reaches persistence or the outbox.  The guard performs
        # the Board 8 action/resource/parameter/freeze recheck before acceptance.
        token_id = self.token_guard.inspect_and_bind(command)
        payload = self._erp_payload(command, party_mapping.external_id, item_mapping.external_id)
        resource = ErpResource(
            resource_type="Sales Order" if command.order_kind == "sales" else "Purchase Order",
            internal_id=command.order_key,
            payload=payload,
            idempotency_key=command.idempotency_key,
        )
        outbox = ExecutionOutboxRow(
            id=new_id(),
            idempotency_key=command.idempotency_key,
            request_hash=request_fingerprint(
                {"operation": "erp.order.upsert", "provider": self.provider}, resource
            ),
            provider=self.provider,
            topic="erp.order.upsert.v1",
            payload_json=resource.model_dump(mode="json"),
            status="queued",
            attempts=0,
        )
        row = OrderCommandRow(
            id=new_id(),
            order_key=command.order_key,
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
            route_id=command.route_id,
            order_kind=command.order_kind,
            customer_entity_id=command.customer_entity_id,
            supplier_entity_id=command.supplier_entity_id,
            item_ref=command.item_ref,
            quantity=quantity(command.quantity),
            quantity_unit=command.quantity_unit,
            unit_price=command.unit_price,
            currency=command.currency,
            terms_json=command.terms,
            commitment_claim_id=command.commitment.claim_id,
            commitment_evidence_ids_json=command.commitment.evidence_fragment_ids,
            policy_decision_id=command.policy_decision_id,
            approval_request_id=command.approval_request_id,
            token_id=token_id,
            params_hash=payload_hash(command.token_params()),
            requested_by=command.requested_by,
            status="queued",
            outbox_id=outbox.id,
        )
        self.session.add_all([outbox, row])
        self.session.commit()
        return row

    def dispatch(self, order_id: str, *, execution_token: str, gateway) -> OrderCommandRow:
        """Perform exactly one ERP effect; retries re-supply the raw token in memory.

        A failed or ambiguous result deliberately leaves Board 8's reservation in
        place.  Retrying the same order and effect key is then safe, while issuing a
        different effect with that token is not.
        """
        row = self.session.get(OrderCommandRow, order_id)
        if row is None:
            raise LookupError(f"order command {order_id} was not found")
        if row.status == "succeeded":
            return row
        command = OrderCommand(
            order_key=row.order_key,
            idempotency_key=row.idempotency_key,
            route_id=row.route_id,
            order_kind=row.order_kind,
            customer_entity_id=row.customer_entity_id,
            supplier_entity_id=row.supplier_entity_id,
            item_ref=row.item_ref,
            quantity=row.quantity,
            quantity_unit=row.quantity_unit,
            unit_price=row.unit_price,
            currency=row.currency,
            terms=row.terms_json,
            commitment={
                "claim_id": row.commitment_claim_id,
                "evidence_fragment_ids": row.commitment_evidence_ids_json,
            },
            policy_decision_id=row.policy_decision_id,
            approval_request_id=row.approval_request_id,
            execution_token=execution_token,
            requested_by=row.requested_by,
        )
        token_id = self.token_guard.inspect_and_bind(command)
        if token_id != row.token_id:
            raise PermissionError("provided token is not the token bound to this order command")
        effect_key = f"order:{row.order_key}"
        self.token_guard.reserve(command, effect_key)
        resource = ErpResource.model_validate(
            self.session.get(ExecutionOutboxRow, row.outbox_id).payload_json
        )
        result = gateway.upsert(resource)
        outbox = self.session.get(ExecutionOutboxRow, row.outbox_id)
        outbox.attempts += 1
        outbox.result_json, outbox.last_error = result.model_dump(mode="json"), result.detail
        self.session.add(
            ExecutionOutboxAttemptRow(
                id=new_id(),
                outbox_id=outbox.id,
                attempt_no=outbox.attempts,
                status=result.state,
                error=result.detail,
                result_json=outbox.result_json,
            )
        )
        if result.state == "succeeded" and result.external_id:
            mapping = self.session.scalar(
                select(ErpMappingRow).where(
                    ErpMappingRow.provider == self.provider,
                    ErpMappingRow.resource_type == resource.resource_type,
                    ErpMappingRow.internal_id == resource.internal_id,
                )
            )
            if mapping is None:
                self.session.add(
                    ErpMappingRow(
                        id=new_id(),
                        provider=self.provider,
                        resource_type=resource.resource_type,
                        internal_id=resource.internal_id,
                        external_id=result.external_id,
                        idempotency_key=resource.idempotency_key,
                        request_hash=request_fingerprint(
                            {"operation": "erp.map", "provider": self.provider}, resource
                        ),
                    )
                )
            self.token_guard.consume(execution_token, effect_key, result.external_id)
            row.external_order_id, row.status, outbox.status = (
                result.external_id,
                "succeeded",
                "succeeded",
            )
        else:
            # keep reservation for exact-key retry/reconciliation; do not consume.
            row.status = (
                "retry" if result.retryable else "ambiguous" if result.ambiguous else "failed"
            )
            outbox.status = row.status
        self.session.commit()
        return row

    def _require_commitment(self, command: OrderCommand) -> None:
        claim = self.session.get(ClaimRow, command.commitment.claim_id)
        if claim is None or claim.status != "verified":
            raise ValueError("a verified commitment Claim is required")
        found = set(
            self.session.scalars(
                select(ClaimEvidenceRow.fragment_id).where(ClaimEvidenceRow.claim_id == claim.id)
            )
        )
        if not set(command.commitment.evidence_fragment_ids).issubset(found):
            raise ValueError("commitment evidence must belong to the commitment Claim")

    def _require_erp_mappings(self, command: OrderCommand) -> tuple[ErpMappingRow, ErpMappingRow]:
        party_type = "Customer" if command.order_kind == "sales" else "Supplier"
        party_id = (
            command.customer_entity_id
            if command.order_kind == "sales"
            else command.supplier_entity_id
        )
        party = self.session.scalar(
            select(ErpMappingRow).where(
                ErpMappingRow.provider == self.provider,
                ErpMappingRow.resource_type == party_type,
                ErpMappingRow.internal_id == party_id,
            )
        )
        item = self.session.scalar(
            select(ErpMappingRow).where(
                ErpMappingRow.provider == self.provider,
                ErpMappingRow.resource_type == "Item",
                ErpMappingRow.internal_id == command.item_ref,
            )
        )
        if party is None or item is None:
            raise ValueError("customer/supplier and item must have ERP mappings before order issue")
        return party, item

    @staticmethod
    def _erp_payload(command: OrderCommand, party_external_id: str, item_external_id: str) -> dict:
        party_key = "customer" if command.order_kind == "sales" else "supplier"
        return {
            party_key: party_external_id,
            "currency": command.currency,
            "items": [
                {
                    "item_code": item_external_id,
                    "qty": str(quantity(command.quantity)),
                    "rate": str(command.unit_price),
                    "uom": command.quantity_unit,
                }
            ],
        }


class OrderReconciliationService:
    FIELDS = ("status", "quantity", "quantity_unit", "currency", "terms_json")

    def __init__(self, session: Session):
        self.session = session

    def ingest(self, event: ErpOrderEvent) -> OrderSnapshotRow:
        existing = self.session.scalar(
            select(OrderSnapshotRow).where(
                OrderSnapshotRow.provider == event.provider,
                OrderSnapshotRow.external_event_id == event.external_event_id,
            )
        )
        if existing:
            return existing
        local = self.session.scalar(
            select(OrderCommandRow).where(
                OrderCommandRow.external_order_id == event.external_order_id
            )
        )
        candidate = {
            "status": event.status,
            "quantity": quantity(event.quantity),
            "quantity_unit": event.quantity_unit,
            "currency": event.currency,
            "terms_json": event.terms,
        }
        expected = (
            None
            if local is None
            else {
                "order_kind": local.order_kind,
                "quantity": local.quantity,
                "quantity_unit": local.quantity_unit,
                "currency": local.currency,
                "terms_json": local.terms_json,
            }
        )
        received = {"order_kind": event.order_kind, **candidate}
        # Status is an ERP fact and normally progresses.  Only commercial terms
        # bound by the committed command can require a human reconciliation.
        conflicts = (
            {}
            if expected is None
            else {
                field: {"expected": str(value), "received": str(received[field])}
                for field, value in expected.items()
                if value != received[field]
            }
        )
        row = OrderSnapshotRow(
            id=new_id(),
            provider=event.provider,
            external_event_id=event.external_event_id,
            external_order_id=event.external_order_id,
            order_kind=event.order_kind,
            occurred_at=aware(event.occurred_at),
            reconciliation_status=(
                "unmapped" if local is None else "review" if conflicts else "reconciled"
            ),
            **candidate,
        )
        self.session.add(row)
        if local is None:
            self.session.add(
                ExecutionReviewIssueRow(
                    id=new_id(),
                    issue_type="unmapped_order_event",
                    resource_ref=f"{event.provider}:{event.external_order_id}",
                    details_json={"external_event_id": event.external_event_id},
                )
            )
        elif conflicts:
            self.session.add(
                ExecutionReviewIssueRow(
                    id=new_id(),
                    issue_type="order_snapshot_conflict",
                    resource_ref=f"{event.provider}:{event.external_order_id}",
                    details_json=conflicts,
                )
            )
        self.session.commit()
        return row
