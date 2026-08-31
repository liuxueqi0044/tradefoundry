"""Ports kept deliberately small so ERP effects stay replaceable and mockable."""

from __future__ import annotations

from typing import Protocol

from tradefoundry.controltower.contracts import ExecutionConsumption, ExecutionReservation
from tradefoundry.controltower.governance import ExecutionTokenService
from tradefoundry.controltower.models import ApprovalRequestRow
from tradefoundry.execution.contracts_orders import ErpEffectResult, ErpResource, OrderCommand
from tradefoundry.ingestion.hashing import payload_hash


class ErpGateway(Protocol):
    def upsert(self, resource: ErpResource) -> ErpEffectResult: ...


class Board8TokenGuard(Protocol):
    def inspect_and_bind(self, command: OrderCommand) -> str: ...

    def reserve(self, command: OrderCommand, effect_key: str) -> None: ...

    def consume(self, raw_token: str, effect_key: str, external_reference: str) -> None: ...


class DisabledTokenGuard:
    """Safe default: a caller must explicitly wire Board 8's authority."""

    def inspect_and_bind(self, command: OrderCommand) -> str:
        raise PermissionError("Board 8 token guard is not configured")

    def reserve(self, command: OrderCommand, effect_key: str) -> None:
        raise PermissionError("Board 8 token guard is not configured")

    def consume(self, raw_token: str, effect_key: str, external_reference: str) -> None:
        raise PermissionError("Board 8 token guard is not configured")


class ControlTowerTokenGuard:
    """Thin Board 8 adapter: validates authority but never reimplements policy."""

    ACTION = "create_order"
    RESOURCE_TYPE = "order"

    def __init__(self, tokens: ExecutionTokenService):
        self.tokens = tokens

    def inspect_and_bind(self, command: OrderCommand) -> str:
        row = self.tokens.inspect(command.execution_token)
        approval = self.tokens.session.get(ApprovalRequestRow, row.approval_request_id)
        if (
            approval is None
            or row.approval_request_id != command.approval_request_id
            or approval.policy_decision_id != command.policy_decision_id
            or approval.requester != command.requested_by
            or row.action != self.ACTION
            or row.resource_type != self.RESOURCE_TYPE
            or row.resource_id != command.order_key
            or row.params_hash != payload_hash(command.token_params())
        ):
            raise PermissionError("Board 8 token is not bound to this exact order action")
        return row.id

    def reserve(self, command: OrderCommand, effect_key: str) -> None:
        self.tokens.reserve(
            ExecutionReservation(
                token=command.execution_token,
                action=self.ACTION,
                resource_type=self.RESOURCE_TYPE,
                resource_id=command.order_key,
                params=command.token_params(),
                effect_key=effect_key,
            )
        )

    def consume(self, raw_token: str, effect_key: str, external_reference: str) -> None:
        self.tokens.consume(
            ExecutionConsumption(
                token=raw_token,
                effect_key=effect_key,
                execution_reference=external_reference,
            )
        )
