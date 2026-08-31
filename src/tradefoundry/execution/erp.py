"""ERPNext REST adapter and durable outbox dispatcher.

The adapter accepts an injected HTTPX transport for deterministic contract tests.  It
never accepts or persists credentials; authentication belongs to runtime transport
configuration / a secret manager.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import idempotent_row, new_id, request_fingerprint, utcnow
from tradefoundry.execution.contracts_orders import ErpEffectResult, ErpResource
from tradefoundry.execution.models_orders import (
    ErpMappingRow,
    ExecutionOutboxAttemptRow,
    ExecutionOutboxRow,
)


class ErpNextHttpxGateway:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        auth_headers: Mapping[str, str] | None = None,
        enabled: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.auth_headers = dict(auth_headers or {})
        self.enabled = enabled

    @property
    def live_effect(self) -> bool:
        return self.enabled

    def upsert(self, resource: ErpResource) -> ErpEffectResult:
        if not self.enabled:
            return ErpEffectResult(
                state="disabled", retryable=False, detail="external ERP is disabled"
            )
        try:
            with httpx.Client(
                base_url=self.base_url, transport=self.transport, timeout=10
            ) as client:
                response = client.post(
                    f"/api/resource/{resource.resource_type}",
                    json=resource.payload,
                    headers={**self.auth_headers, "Idempotency-Key": resource.idempotency_key},
                )
        except httpx.TimeoutException as error:
            # The write may have completed before its response was lost.  It must be
            # reconciled by the ERP idempotency/reference lookup, never duplicated.
            return ErpEffectResult(state="ambiguous", ambiguous=True, detail=str(error))
        except httpx.ConnectError as error:
            return ErpEffectResult(state="unavailable", retryable=True, detail=str(error))
        if response.status_code >= 500:
            return ErpEffectResult(state="ambiguous", ambiguous=True, detail=response.text[:500])
        if response.status_code >= 400:
            return ErpEffectResult(state="rejected", detail=response.text[:500])
        data = response.json().get("data", response.json())
        external_id = data.get("name") or data.get("id")
        if not external_id:
            return ErpEffectResult(
                state="ambiguous", ambiguous=True, detail="ERP response has no identifier"
            )
        return ErpEffectResult(state="succeeded", external_id=str(external_id), payload=data)


class RecordingErpGateway:
    """Fixture-friendly adapter which records intent and optionally delegates."""

    live_effect = False

    def __init__(self, delegate=None, result: ErpEffectResult | None = None):
        self.delegate = delegate
        self.result = result
        self.requests: list[ErpResource] = []

    def upsert(self, resource: ErpResource) -> ErpEffectResult:
        self.requests.append(resource)
        if self.delegate is not None:
            return self.delegate.upsert(resource)
        return self.result or ErpEffectResult(
            state="succeeded", external_id=f"fixture-{resource.internal_id}"
        )


class ErpMappingService:
    def __init__(
        self,
        session: Session,
        gateway,
        *,
        provider: str = "erpnext",
        allow_live_effect: bool = False,
    ):
        self.session, self.gateway, self.provider = session, gateway, provider
        self.allow_live_effect = allow_live_effect

    def queue(self, resource: ErpResource, *, topic: str = "erp.upsert.v1") -> ExecutionOutboxRow:
        request_hash = request_fingerprint(
            {"operation": topic, "provider": self.provider}, resource
        )
        existing = idempotent_row(
            self.session, ExecutionOutboxRow, resource.idempotency_key, request_hash
        )
        if existing:
            return existing
        row = ExecutionOutboxRow(
            id=new_id(),
            idempotency_key=resource.idempotency_key,
            request_hash=request_hash,
            provider=self.provider,
            topic=topic,
            payload_json=resource.model_dump(mode="json"),
            status="queued",
            attempts=0,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def dispatch(self, outbox_id: str) -> ExecutionOutboxRow:
        row = self.session.get(ExecutionOutboxRow, outbox_id)
        if row is None:
            raise LookupError(f"outbox {outbox_id} was not found")
        if row.status == "succeeded":
            return row
        resource = ErpResource.model_validate(row.payload_json)
        mapped = self.session.scalar(
            select(ErpMappingRow).where(
                ErpMappingRow.provider == self.provider,
                ErpMappingRow.resource_type == resource.resource_type,
                ErpMappingRow.internal_id == resource.internal_id,
            )
        )
        if mapped:
            row.attempts += 1
            row.status, row.result_json = "succeeded", {"external_id": mapped.external_id}
            self.session.add(
                ExecutionOutboxAttemptRow(
                    id=new_id(),
                    outbox_id=row.id,
                    attempt_no=row.attempts,
                    status="succeeded",
                    error=None,
                    result_json=row.result_json,
                )
            )
            self.session.commit()
            return row
        if getattr(self.gateway, "live_effect", False) and not self.allow_live_effect:
            raise PermissionError(
                "live master-data sync requires an explicitly authorized operator boundary"
            )
        result = self.gateway.upsert(resource)
        row.attempts += 1
        row.result_json = result.model_dump(mode="json")
        row.last_error = result.detail
        self.session.add(
            ExecutionOutboxAttemptRow(
                id=new_id(),
                outbox_id=row.id,
                attempt_no=row.attempts,
                status=result.state,
                error=result.detail,
                result_json=row.result_json,
            )
        )
        if result.state == "succeeded" and result.external_id:
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
            row.status, row.next_attempt_at = "succeeded", None
        elif result.retryable:
            row.status = "retry"
            row.next_attempt_at = utcnow() + timedelta(minutes=min(60, 2 ** min(row.attempts, 6)))
        else:
            # Ambiguous outcomes are retained for reconciliation, never retried blindly.
            row.status = "ambiguous" if result.ambiguous else "failed"
        self.session.commit()
        return row
