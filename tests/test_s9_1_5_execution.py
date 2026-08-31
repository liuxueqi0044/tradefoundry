from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from tradefoundry.deals.models import DealRouteRow
from tradefoundry.evidence.models import ClaimEvidenceRow
from tradefoundry.execution.common import new_id
from tradefoundry.execution.contracts_orders import (
    CommitmentEvidence,
    ErpEffectResult,
    ErpOrderEvent,
    ErpResource,
    MilestoneRecord,
    OrderCommand,
    ShipmentDocument,
)
from tradefoundry.execution.documents import ShipmentDocumentService
from tradefoundry.execution.erp import (
    ErpMappingService,
    ErpNextHttpxGateway,
    RecordingErpGateway,
)
from tradefoundry.execution.fulfillment import FulfillmentService
from tradefoundry.execution.models_orders import (
    ErpMappingRow,
    ExecutionOutboxAttemptRow,
    ExecutionOutboxRow,
    ExecutionReviewIssueRow,
)
from tradefoundry.execution.orders import OrderReconciliationService, OrderService


class Guard:
    def __init__(self):
        self.reservations = []
        self.consumptions = []

    def inspect_and_bind(self, command):
        return "board8-token-id"

    def reserve(self, command, effect_key):
        self.reservations.append((command.order_key, effect_key))

    def consume(self, raw_token, effect_key, external_reference):
        self.consumptions.append((raw_token, effect_key, external_reference))


def order(session, claim, route, *, key="order-1", idempotency_key="order-idempotency"):
    route_row = session.get(DealRouteRow, route.id)
    route_row.stage = "committed"
    session.commit()
    return OrderCommand(
        order_key=key,
        idempotency_key=idempotency_key,
        route_id=route.id,
        order_kind="sales",
        customer_entity_id="buyer-1",
        item_ref="item:valve",
        quantity=Decimal("10"),
        quantity_unit="each",
        unit_price=Decimal("12.50"),
        currency="usd",
        terms={"incoterm": "FOB"},
        commitment=CommitmentEvidence(
            claim_id=claim.id, evidence_fragment_ids=[claim_evidence_id(session, claim)]
        ),
        policy_decision_id="policy-1",
        approval_request_id="approval-1",
        execution_token="raw-token-is-memory-only",
        requested_by="operator-1",
    )


def claim_evidence_id(session, claim):
    return session.scalar(
        select(ClaimEvidenceRow.fragment_id).where(ClaimEvidenceRow.claim_id == claim.id)
    )


def add_order_mappings(session):
    for resource_type, internal_id, external_id in (
        ("Customer", "buyer-1", "ERP-BUYER"),
        ("Item", "item:valve", "ERP-VALVE"),
    ):
        session.add(
            ErpMappingRow(
                id=new_id(),
                provider="erpnext",
                resource_type=resource_type,
                internal_id=internal_id,
                external_id=external_id,
                idempotency_key=f"mapping-{resource_type}",
                request_hash="a" * 64,
            )
        )
    session.commit()


def test_s9_1_erp_unavailable_is_retained_for_retry_and_mapping_is_idempotent(session):
    gateway = RecordingErpGateway(result=ErpEffectResult(state="unavailable", retryable=True))
    assert gateway.live_effect is False
    service = ErpMappingService(session, gateway)
    resource = ErpResource(
        resource_type="Customer",
        internal_id="entity-1",
        payload={"customer_name": "Acme"},
        idempotency_key="customer-1",
    )
    queued = service.queue(resource)
    assert service.dispatch(queued.id).status == "retry"
    gateway.result = ErpEffectResult(state="succeeded", external_id="CUST-001")
    completed = service.dispatch(queued.id)
    assert completed.status == "succeeded"
    assert len(gateway.requests) == 2
    assert service.queue(resource).id == queued.id
    assert len(list(session.scalars(select(ExecutionOutboxAttemptRow)))) == 2


def test_s9_1_erpnext_http_contract_uses_runtime_auth_and_quarantines_timeout():
    resource = ErpResource(
        resource_type="Customer",
        internal_id="entity-http",
        payload={"customer_name": "HTTP Fixture"},
        idempotency_key="customer-http",
    )

    def success(request: httpx.Request):
        assert request.headers["authorization"] == "token runtime-only"
        assert request.headers["idempotency-key"] == "customer-http"
        return httpx.Response(200, json={"data": {"name": "CUST-HTTP"}})

    gateway = ErpNextHttpxGateway(
        "https://erp.example.invalid",
        transport=httpx.MockTransport(success),
        auth_headers={"Authorization": "token runtime-only"},
        enabled=True,
    )
    result = gateway.upsert(resource)
    assert result.state == "succeeded" and result.external_id == "CUST-HTTP"

    def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("response lost", request=request)

    ambiguous = ErpNextHttpxGateway(
        "https://erp.example.invalid",
        transport=httpx.MockTransport(timeout),
        enabled=True,
    ).upsert(resource)
    assert ambiguous.state == "ambiguous" and ambiguous.ambiguous


def test_s9_1_erpnext_failure_taxonomy_and_live_master_data_guard(session):
    resource = ErpResource(
        resource_type="Customer",
        internal_id="entity-failures",
        payload={"customer_name": "Failure Fixture"},
        idempotency_key="customer-failures",
    )
    disabled = ErpNextHttpxGateway("https://erp.example.invalid").upsert(resource)
    assert disabled.state == "disabled"

    def response(status: int, body: dict | None = None):
        return httpx.MockTransport(
            lambda _request: httpx.Response(status, json=body or {"message": "failure"})
        )

    assert ErpNextHttpxGateway(
        "https://erp.example.invalid", transport=response(503), enabled=True
    ).upsert(resource).ambiguous
    assert (
        ErpNextHttpxGateway(
            "https://erp.example.invalid", transport=response(422), enabled=True
        ).upsert(resource).state
        == "rejected"
    )
    assert ErpNextHttpxGateway(
        "https://erp.example.invalid",
        transport=response(200, {"data": {"customer_name": "missing id"}}),
        enabled=True,
    ).upsert(resource).ambiguous

    def connect_error(request: httpx.Request):
        raise httpx.ConnectError("not connected", request=request)

    assert ErpNextHttpxGateway(
        "https://erp.example.invalid",
        transport=httpx.MockTransport(connect_error),
        enabled=True,
    ).upsert(resource).retryable

    live = ErpMappingService(
        session,
        ErpNextHttpxGateway(
            "https://erp.example.invalid", transport=response(200), enabled=True
        ),
    )
    queued = live.queue(resource)
    with pytest.raises(PermissionError, match="authorized operator"):
        live.dispatch(queued.id)


def test_s9_2_commitment_idempotency_outbox_and_token_lifecycle(
    session, master_claim_factory, deal_route_factory
):
    claim = master_claim_factory(verified=True)
    _, route = deal_route_factory()
    add_order_mappings(session)
    guard = Guard()
    service = OrderService(session, guard)
    command = order(session, claim, route)
    issued = service.issue(command)
    assert service.issue(command).id == issued.id
    outbox = session.get(ExecutionOutboxRow, issued.outbox_id)
    assert "raw-token-is-memory-only" not in str(outbox.payload_json)
    assert outbox.payload_json["payload"] == {
        "customer": "ERP-BUYER",
        "currency": "USD",
        "items": [{"item_code": "ERP-VALVE", "qty": "10.000000", "rate": "12.50", "uom": "each"}],
    }
    unavailable = RecordingErpGateway(result=ErpEffectResult(state="unavailable", retryable=True))
    assert (
        service.dispatch(
            issued.id, execution_token=command.execution_token, gateway=unavailable
        ).status
        == "retry"
    )
    assert not guard.consumptions
    available = RecordingErpGateway(result=ErpEffectResult(state="succeeded", external_id="SO-001"))
    assert (
        service.dispatch(
            issued.id, execution_token=command.execution_token, gateway=available
        ).status
        == "succeeded"
    )
    assert guard.reservations == [("order-1", "order:order-1"), ("order-1", "order:order-1")]
    assert guard.consumptions == [("raw-token-is-memory-only", "order:order-1", "SO-001")]
    assert len(list(session.scalars(select(ExecutionOutboxAttemptRow)))) == 2


def test_s9_2_purchase_order_uses_supplier_mapping_and_native_erp_payload(
    session, master_claim_factory, deal_route_factory
):
    claim = master_claim_factory(verified=True)
    _, route = deal_route_factory()
    route_row = session.get(DealRouteRow, route.id)
    route_row.stage = "committed"
    for resource_type, internal_id, external_id in (
        ("Supplier", "supplier-1", "ERP-SUPPLIER"),
        ("Item", "item:pump", "ERP-PUMP"),
    ):
        session.add(
            ErpMappingRow(
                id=new_id(),
                provider="erpnext",
                resource_type=resource_type,
                internal_id=internal_id,
                external_id=external_id,
                idempotency_key=f"purchase-map-{resource_type}",
                request_hash="b" * 64,
            )
        )
    session.commit()
    issued = OrderService(session, Guard()).issue(
        OrderCommand(
            order_key="purchase-order-1",
            idempotency_key="purchase-order-1",
            route_id=route.id,
            order_kind="purchase",
            supplier_entity_id="supplier-1",
            item_ref="item:pump",
            quantity=Decimal("2"),
            quantity_unit="each",
            unit_price=Decimal("50"),
            currency="USD",
            commitment=CommitmentEvidence(
                claim_id=claim.id,
                evidence_fragment_ids=[claim_evidence_id(session, claim)],
            ),
            policy_decision_id="policy-purchase",
            approval_request_id="approval-purchase",
            execution_token="purchase-token",
            requested_by="operator-1",
        )
    )
    outbox = session.get(ExecutionOutboxRow, issued.outbox_id)
    assert outbox.payload_json["resource_type"] == "Purchase Order"
    assert outbox.payload_json["payload"]["supplier"] == "ERP-SUPPLIER"


def test_s9_3_immutable_snapshots_allow_status_progression_but_raise_term_conflicts(
    session, master_claim_factory, deal_route_factory
):
    claim = master_claim_factory(verified=True)
    _, route = deal_route_factory()
    add_order_mappings(session)
    service = OrderService(session, Guard())
    command = order(session, claim, route)
    issued = service.issue(command)
    service.dispatch(
        issued.id, execution_token=command.execution_token, gateway=RecordingErpGateway()
    )
    reconciliation = OrderReconciliationService(session)
    event = ErpOrderEvent(
        external_event_id="event-1",
        external_order_id="fixture-order-1",
        order_kind="sales",
        status="submitted",
        quantity=Decimal("10"),
        quantity_unit="each",
        currency="USD",
        terms={"incoterm": "FOB"},
        occurred_at=datetime.now(UTC),
    )
    first = reconciliation.ingest(event)
    advanced = reconciliation.ingest(
        event.model_copy(update={"external_event_id": "event-2", "status": "to_deliver"})
    )
    assert first.reconciliation_status == advanced.reconciliation_status == "reconciled"
    conflict = reconciliation.ingest(
        event.model_copy(update={"external_event_id": "event-3", "currency": "EUR"})
    )
    assert conflict.reconciliation_status == "review"
    assert session.scalar(
        select(ExecutionReviewIssueRow).where(
            ExecutionReviewIssueRow.issue_type == "order_snapshot_conflict"
        )
    )
    unmapped = reconciliation.ingest(
        event.model_copy(
            update={"external_event_id": "event-4", "external_order_id": "unknown-order"}
        )
    )
    assert unmapped.reconciliation_status == "unmapped"


def test_s9_4_milestones_are_evidence_backed_partial_and_late(session, master_claim_factory):
    claim = master_claim_factory(verified=True)
    now = datetime.now(UTC)
    service = FulfillmentService(session)
    record = MilestoneRecord(
        shipment_id="shipment-1",
        milestone_key="delivery",
        version_no=1,
        planned_at=now,
        actual_at=now + timedelta(days=2, hours=4),
        planned_quantity=Decimal("10"),
        actual_quantity=Decimal("4"),
        quantity_unit="each",
        evidence=CommitmentEvidence(
            claim_id=claim.id, evidence_fragment_ids=[claim_evidence_id(session, claim)]
        ),
    )
    row = service.record(record)
    assert row.delivery_status == "partial"
    assert row.late_days == 2
    assert service.record(record).id == row.id
    with pytest.raises(ValueError, match="milestone version"):
        service.record(record.model_copy(update={"actual_quantity": Decimal("5")}))


def test_s9_5_document_sets_report_gaps_and_redact_sensitive_refs(session, master_claim_factory):
    service = ShipmentDocumentService(session)
    now = datetime.now(UTC)
    claim = master_claim_factory(verified=True)
    evidence = CommitmentEvidence(
        claim_id=claim.id, evidence_fragment_ids=[claim_evidence_id(session, claim)]
    )
    invoice_request = ShipmentDocument(
        shipment_id="shipment-1",
        document_type="invoice",
        version_no=1,
        storage_ref="s3://secret/invoice.pdf",
        content_hash="a" * 64,
        evidence=evidence,
        expires_at=now - timedelta(days=1),
        related_document_versions={"packing_list": 2},
        sensitive_fields={"bank_account": "123456"},
    )
    invoice = service.add(invoice_request)
    assert service.add(invoice_request).id == invoice.id
    with pytest.raises(ValueError, match="document version"):
        service.add(invoice_request.model_copy(update={"content_hash": "c" * 64}))
    service.add(
        ShipmentDocument(
            shipment_id="shipment-1",
            document_type="packing_list",
            version_no=1,
            storage_ref="s3://secret/packing.pdf",
            content_hash="b" * 64,
            evidence=evidence,
        )
    )
    issue_types = {issue.issue_type for issue in service.validate("shipment-1", now=now)}
    assert {
        "missing_documents",
        "expired_documents",
        "document_version_inconsistency",
    } <= issue_types
    redacted = service.view(invoice.id, roles=set())
    assert redacted["storage_ref"] == redacted["sensitive_fields"]["bank_account"] == "[REDACTED]"
    assert service.view(invoice.id, roles={"execution_sensitive_reader"})["storage_ref"].startswith(
        "s3://"
    )
