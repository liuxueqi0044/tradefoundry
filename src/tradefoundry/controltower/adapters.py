from __future__ import annotations

from sqlalchemy.orm import Session

from tradefoundry.bilateral.contracts import (
    AuthorizationContext,
    CostScenario,
    EligibilityRequest,
    PolicyAuthorization,
)
from tradefoundry.bilateral.ports import ExecutionBinding, OutboundPayload
from tradefoundry.controltower.contracts import (
    ExecutionConsumption,
    ExecutionReservation,
    PolicyDecisionCreate,
)
from tradefoundry.controltower.governance import ExecutionTokenService
from tradefoundry.controltower.models import LandedCostScenarioRow
from tradefoundry.controltower.policy import PolicyEngine
from tradefoundry.ingestion.hashing import payload_hash


class Board7CostScenarioAdapter:
    def __init__(self, session: Session):
        self.session = session

    def get(self, reference: str) -> CostScenario:
        row = self.session.get(LandedCostScenarioRow, reference)
        if row is None:
            raise ValueError(
                f"Board 8 landed cost scenario {reference} was not found or is unavailable"
            )
        if row.status == "incomplete":
            raise ValueError("incomplete landed cost scenario cannot price a buyer quote")
        return CostScenario(
            reference=row.id,
            snapshot_hash=row.input_hash,
            calculator_version=row.calculator_version,
            status=row.status,
            total_cost=row.total_base,
            currency=row.currency,
            quantity=row.quantity,
            quantity_unit=row.quantity_unit,
            assumptions=row.assumptions_json,
        )


class Board7PolicyAdapter:
    """Routes legacy Board 7 policy ports through the one Board 8 decision service."""

    def __init__(self, session: Session, bundle_key: str = "tradefoundry-actions"):
        self.policy = PolicyEngine(session)
        self.bundle_key = bundle_key

    def authorize(self, context: AuthorizationContext) -> PolicyAuthorization:
        params = {
            "recipient_ref": context.recipient_ref,
            "payload_hash": context.payload_hash,
        }
        try:
            decision = self.policy.decide(
                PolicyDecisionCreate(
                    bundle_key=self.bundle_key,
                    idempotency_key=(
                        f"board7:{context.action_kind}:{context.resource_id}:"
                        f"{context.payload_hash}:{context.requested_by}"
                    ),
                    actor=context.requested_by,
                    action=context.action_kind,
                    resource_type=(
                        "message_draft" if context.action_kind == "first_buyer_contact" else "rfq"
                    ),
                    resource_id=context.resource_id,
                    context={
                        "params_hash": payload_hash(params),
                        "recipient_ref": context.recipient_ref,
                        "payload_hash": context.payload_hash,
                        "supplier_whitelisted": context.supplier_whitelisted,
                        "eligibility_decision_id": context.eligibility_decision_id,
                    },
                )
            )
        except ValueError as exc:
            if "no active policy bundle" not in str(exc):
                raise
            return self._unconfigured()
        return PolicyAuthorization(
            decision=decision.decision,
            policy_decision_ref=decision.id,
            policy_version=decision.policy_version,
            approved_by=(f"policy:{decision.id}" if decision.decision == "allow" else None),
            reasons=decision.reasons_json,
        )

    def communication_eligibility(
        self, *, contact_id: str, request: EligibilityRequest
    ) -> PolicyAuthorization:
        try:
            decision = self.policy.decide(
                PolicyDecisionCreate(
                    bundle_key=self.bundle_key,
                    idempotency_key=f"board7:{request.idempotency_key}:policy",
                    actor=str(request.context.get("actor") or "board7-eligibility"),
                    action="communication_eligibility",
                    resource_type="contact",
                    resource_id=contact_id,
                    context={
                        **request.context,
                        "channel": request.channel,
                        "jurisdiction": request.jurisdiction,
                        "purpose": request.purpose,
                        "first_contact": request.purpose == "first_contact",
                        "evaluated_at": request.evaluated_at.isoformat(),
                    },
                )
            )
        except ValueError as exc:
            if "no active policy bundle" not in str(exc):
                raise
            return self._unconfigured()
        return PolicyAuthorization(
            decision=decision.decision,
            policy_decision_ref=decision.id,
            policy_version=decision.policy_version,
            approved_by=(f"policy:{decision.id}" if decision.decision == "allow" else None),
            reasons=decision.reasons_json,
        )

    @staticmethod
    def _unconfigured() -> PolicyAuthorization:
        return PolicyAuthorization(
            decision="deny",
            policy_decision_ref="board8:not-connected",
            policy_version="deny-all-v1",
            reasons=["Board 8 has no active reviewed policy bundle; default deny applied."],
        )


class Board7ExecutionGuard:
    def __init__(self, session: Session):
        self.tokens = ExecutionTokenService(session)

    def inspect(self, raw_token: str) -> ExecutionBinding:
        row = self.tokens.inspect(raw_token)
        params = row.params_json
        recipient = params.get("recipient_ref")
        payload = params.get("payload_hash")
        resource_version = params.get("resource_version")
        if not isinstance(recipient, str) or not recipient:
            raise ValueError("control token is missing recipient_ref binding")
        if not isinstance(payload, str) or len(payload) != 64:
            raise ValueError("control token is missing payload_hash binding")
        if not isinstance(resource_version, int) or resource_version < 1:
            raise ValueError("control token is missing resource_version binding")
        return ExecutionBinding(
            token_id=row.id,
            action_kind=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            recipient_ref=recipient,
            payload_hash=payload,
            resource_version=resource_version,
            params=params,
        )

    def reserve(
        self,
        raw_token: str,
        binding: ExecutionBinding,
        payload: OutboundPayload,
        effect_key: str,
    ) -> None:
        if (
            payload.action_kind != binding.action_kind
            or payload.resource_id != binding.resource_id
            or payload.resource_version != binding.resource_version
            or payload.recipient_ref != binding.recipient_ref
            or payload.payload_hash != binding.payload_hash
        ):
            raise ValueError("current outbound payload differs from the control-token binding")
        self.tokens.reserve(
            ExecutionReservation(
                token=raw_token,
                action=binding.action_kind,
                resource_type=binding.resource_type,
                resource_id=binding.resource_id,
                params=binding.params,
                effect_key=effect_key,
            )
        )

    def consume(self, raw_token: str, effect_key: str, execution_reference: str) -> None:
        self.tokens.consume(
            ExecutionConsumption(
                token=raw_token,
                effect_key=effect_key,
                execution_reference=execution_reference,
            )
        )
