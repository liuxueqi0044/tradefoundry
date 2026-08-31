"""Versioned, provider-neutral contracts for Board 9 execution facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _currency(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency must be a three-letter ISO 4217 code")
    return value


class CommitmentEvidence(ExecutionModel):
    claim_id: str = Field(min_length=1)
    evidence_fragment_ids: list[str] = Field(min_length=1)


class OrderCommand(ExecutionModel):
    order_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    route_id: str = Field(min_length=1)
    order_kind: str
    customer_entity_id: str | None = None
    supplier_entity_id: str | None = None
    item_ref: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    quantity_unit: str = Field(min_length=1, max_length=30)
    unit_price: Decimal = Field(ge=0)
    currency: str
    terms: dict[str, Any] = Field(default_factory=dict)
    commitment: CommitmentEvidence
    policy_decision_id: str = Field(min_length=1)
    approval_request_id: str = Field(min_length=1)
    execution_token: str = Field(min_length=1)
    requested_by: str = Field(min_length=1, max_length=160)

    @field_validator("order_kind")
    @classmethod
    def valid_order_kind(cls, value: str) -> str:
        if value not in {"sales", "purchase"}:
            raise ValueError("order_kind must be sales or purchase")
        return value

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return _currency(value)

    @model_validator(mode="after")
    def required_party(self):
        if self.order_kind == "sales" and not self.customer_entity_id:
            raise ValueError("sales orders require customer_entity_id")
        if self.order_kind == "purchase" and not self.supplier_entity_id:
            raise ValueError("purchase orders require supplier_entity_id")
        return self

    def token_params(self) -> dict[str, Any]:
        """The exact business parameters Board 8 must have authorized."""
        params = self.model_dump(
            mode="json",
            exclude={
                "idempotency_key",
                "policy_decision_id",
                "approval_request_id",
                "execution_token",
            },
        )
        # Canonical fixed precision survives the SQL Numeric round-trip between
        # token issuance and external dispatch.
        params["quantity"] = f"{self.quantity.quantize(Decimal('0.000001')):.6f}"
        params["unit_price"] = f"{self.unit_price.quantize(Decimal('0.0001')):.4f}"
        return params


class ErpResource(ExecutionModel):
    resource_type: str = Field(min_length=1, max_length=80)
    internal_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ErpEffectResult(ExecutionModel):
    state: str
    external_id: str | None = None
    retryable: bool = False
    ambiguous: bool = False
    detail: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class OrderDispatchRequest(ExecutionModel):
    execution_token: str = Field(min_length=1)


class ErpOrderEvent(ExecutionModel):
    provider: str = Field(default="erpnext")
    external_event_id: str = Field(min_length=1, max_length=240)
    external_order_id: str = Field(min_length=1, max_length=240)
    order_kind: str
    status: str = Field(min_length=1, max_length=60)
    quantity: Decimal = Field(ge=0)
    quantity_unit: str = Field(min_length=1, max_length=30)
    currency: str
    terms: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("order_kind")
    @classmethod
    def event_kind(cls, value: str) -> str:
        if value not in {"sales", "purchase"}:
            raise ValueError("order_kind must be sales or purchase")
        return value

    @field_validator("currency")
    @classmethod
    def event_currency(cls, value: str) -> str:
        return _currency(value)


class MilestoneRecord(ExecutionModel):
    shipment_id: str = Field(min_length=1)
    milestone_key: str = Field(min_length=1, max_length=100)
    version_no: int = Field(ge=1)
    planned_at: datetime
    actual_at: datetime | None = None
    planned_quantity: Decimal = Field(gt=0)
    actual_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    quantity_unit: str = Field(min_length=1, max_length=30)
    evidence: CommitmentEvidence

    @model_validator(mode="after")
    def quantity_not_over_plan(self):
        if self.actual_quantity > self.planned_quantity:
            raise ValueError("actual_quantity cannot exceed planned_quantity")
        return self


class ShipmentDocument(ExecutionModel):
    shipment_id: str = Field(min_length=1)
    document_type: str
    version_no: int = Field(ge=1)
    storage_ref: str = Field(min_length=1, max_length=500)
    content_hash: str = Field(min_length=8, max_length=128)
    evidence: CommitmentEvidence
    expires_at: datetime | None = None
    related_document_versions: dict[str, int] = Field(default_factory=dict)
    sensitive_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_type")
    @classmethod
    def type_allowed(cls, value: str) -> str:
        if value not in {"invoice", "packing_list", "bill_of_lading", "customs", "certificate"}:
            raise ValueError("unsupported shipment document type")
        return value
