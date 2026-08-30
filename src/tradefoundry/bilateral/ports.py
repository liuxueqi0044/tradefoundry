from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from tradefoundry.bilateral.contracts import (
    AuthorizationContext,
    CostScenario,
    EligibilityRequest,
    PolicyAuthorization,
)


class PolicyDecisionPort(Protocol):
    def authorize(self, context: AuthorizationContext) -> PolicyAuthorization: ...

    def communication_eligibility(
        self, *, contact_id: str, request: EligibilityRequest
    ) -> PolicyAuthorization: ...


class DenyAllPolicyPort:
    """Production-safe Board 7 default until Board 8 provides real policy decisions."""

    def authorize(self, context: AuthorizationContext) -> PolicyAuthorization:
        return PolicyAuthorization(
            decision="deny",
            policy_decision_ref="board8:not-connected",
            policy_version="deny-all-v1",
            reasons=["Board 8 policy and approval service is not connected."],
        )

    def communication_eligibility(
        self, *, contact_id: str, request: EligibilityRequest
    ) -> PolicyAuthorization:
        return PolicyAuthorization(
            decision="deny",
            policy_decision_ref="board8:not-connected",
            policy_version="deny-all-v1",
            reasons=["Board 8 communication policy is not connected."],
        )


class CostScenarioPort(Protocol):
    def get(self, reference: str) -> CostScenario: ...


class UnavailableCostScenarioPort:
    def get(self, reference: str) -> CostScenario:
        raise ValueError("Board 8 deterministic cost service is not connected")


@dataclass(frozen=True)
class OutboundPayload:
    action_kind: str
    resource_id: str
    resource_version: int
    recipient_ref: str
    subject: str
    body: str
    payload_hash: str


@dataclass(frozen=True)
class OutboundReceipt:
    gateway_name: str
    external_message_id: str
    status: str
    details: dict[str, Any]


class OutboundGateway(Protocol):
    name: str

    def send(self, payload: OutboundPayload, *, effect_key: str) -> OutboundReceipt: ...


class DisabledOutboundGateway:
    name = "disabled"

    def send(self, payload: OutboundPayload, *, effect_key: str) -> OutboundReceipt:
        raise ValueError("live outbound gateway is disabled at the Board 7 production gate")
