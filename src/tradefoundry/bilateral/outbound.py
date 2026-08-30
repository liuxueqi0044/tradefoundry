from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    aware,
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import (
    AuthorizationContext,
    SendCommand,
    SendTokenView,
)
from tradefoundry.bilateral.models import (
    EligibilityDecisionRow,
    MessageDraftRow,
    OutboundMessageRow,
    RfqVersionRow,
    SendTokenRow,
    SupplierCandidateRow,
    SuppressionRow,
)
from tradefoundry.bilateral.ports import OutboundGateway, OutboundPayload, PolicyDecisionPort
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.ingestion.models import utcnow


class OutboundAuthorizationService:
    def __init__(self, session: Session, policy: PolicyDecisionPort):
        self.session = session
        self.policy = policy

    def authorize_rfq(
        self, rfq_id: str, supplier_profile_id: str, *, requested_by: str
    ) -> SendTokenView:
        rfq = require_row(self.session, RfqVersionRow, rfq_id, "RFQ")
        if rfq.status != "final":
            raise ValueError("only a final RFQ version can be authorized")
        candidate = self.session.scalar(
            select(SupplierCandidateRow).where(
                SupplierCandidateRow.route_id == rfq.route_id,
                SupplierCandidateRow.supplier_profile_id == supplier_profile_id,
            )
        )
        if candidate is None or candidate.status != "whitelisted":
            raise ValueError("supplier is not whitelisted for this route")
        context = AuthorizationContext(
            action_kind="supplier_rfq",
            resource_id=rfq.id,
            recipient_ref=supplier_profile_id,
            payload_hash=rfq.content_hash,
            supplier_whitelisted=True,
            requested_by=requested_by,
        )
        return self._issue(context)

    def authorize_first_contact(self, draft_id: str, *, requested_by: str) -> SendTokenView:
        draft = require_row(self.session, MessageDraftRow, draft_id, "message draft")
        eligibility = require_row(
            self.session,
            EligibilityDecisionRow,
            draft.eligibility_decision_id,
            "eligibility decision",
        )
        if eligibility.decision != "allow":
            raise ValueError("contact is not eligible for outbound communication")
        self._require_not_suppressed(draft.contact_id, eligibility.channel)
        if draft.prohibited_findings_json:
            raise ValueError("draft contains prohibited or unsupported assertions")
        context = AuthorizationContext(
            action_kind="first_buyer_contact",
            resource_id=draft.id,
            recipient_ref=draft.contact_id,
            payload_hash=draft.content_hash,
            eligibility_decision_id=eligibility.id,
            requested_by=requested_by,
        )
        return self._issue(context)

    def _require_not_suppressed(self, contact_id: str, channel: str) -> None:
        suppression = self.session.scalar(
            select(SuppressionRow).where(
                SuppressionRow.contact_id == contact_id,
                SuppressionRow.active.is_(True),
                SuppressionRow.channel.in_([channel, "all"]),
            )
        )
        if suppression is not None:
            raise ValueError("contact is currently suppressed")

    def _issue(self, context: AuthorizationContext) -> SendTokenView:
        decision = self.policy.authorize(context)
        if decision.decision != "allow" or not decision.approved_by:
            reasons = "; ".join(decision.reasons) or "policy did not allow the action"
            raise ValueError(reasons)
        now = utcnow()
        expiry = decision.expires_at or (now + timedelta(minutes=10))
        if aware(expiry) <= aware(now):
            raise ValueError("policy authorization has already expired")
        raw_token = secrets.token_urlsafe(32)
        row = SendTokenRow(
            id=new_id(),
            token_hash=payload_hash(raw_token),
            action_kind=context.action_kind,
            resource_id=context.resource_id,
            recipient_ref=context.recipient_ref,
            payload_hash=context.payload_hash,
            policy_decision_ref=decision.policy_decision_ref,
            approved_by=decision.approved_by,
            expires_at=expiry,
        )
        self.session.add(row)
        self.session.commit()
        return SendTokenView(
            token=raw_token,
            token_id=row.id,
            action_kind=row.action_kind,
            resource_id=row.resource_id,
            recipient_ref=row.recipient_ref,
            expires_at=row.expires_at,
            policy_decision_ref=row.policy_decision_ref,
        )


class OutboundSendService:
    def __init__(self, session: Session, gateway: OutboundGateway):
        self.session = session
        self.gateway = gateway

    def send(self, request: SendCommand) -> OutboundMessageRow:
        token_hash = payload_hash(request.token)
        request_hash = request_fingerprint(
            {"operation": "outbound.send", "token_hash": token_hash}, request
        )
        existing = idempotent_row(
            self.session, OutboundMessageRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        token = self.session.scalar(
            select(SendTokenRow).where(SendTokenRow.token_hash == token_hash)
        )
        if token is None:
            raise ValueError("send token is invalid")
        if token.consumed_at is not None:
            raise ValueError("send token has already been consumed")
        if aware(token.expires_at) <= aware(utcnow()):
            raise ValueError("send token has expired")
        payload = self._payload(token)
        if payload.payload_hash != token.payload_hash:
            raise ValueError("authorized payload no longer matches the resource")
        effect_key = f"bilateral-send:{token.id}"
        receipt = self.gateway.send(payload, effect_key=effect_key)
        row = OutboundMessageRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            action_kind=payload.action_kind,
            resource_id=payload.resource_id,
            resource_version=payload.resource_version,
            recipient_ref=payload.recipient_ref,
            token_id=token.id,
            gateway_name=receipt.gateway_name,
            external_message_id=receipt.external_message_id,
            receipt_json=receipt.details,
            payload_hash=payload.payload_hash,
            status=receipt.status,
            sent_by=request.actor,
        )
        token.consumed_at = utcnow()
        self.session.add(row)
        self.session.commit()
        return row

    def _payload(self, token: SendTokenRow) -> OutboundPayload:
        if token.action_kind == "supplier_rfq":
            resource = require_row(self.session, RfqVersionRow, token.resource_id, "RFQ")
            if resource.status != "final":
                raise ValueError("RFQ is no longer final")
            candidate = self.session.scalar(
                select(SupplierCandidateRow).where(
                    SupplierCandidateRow.route_id == resource.route_id,
                    SupplierCandidateRow.supplier_profile_id == token.recipient_ref,
                )
            )
            if candidate is None or candidate.status != "whitelisted":
                raise ValueError("supplier is no longer whitelisted for this route")
            return OutboundPayload(
                action_kind=token.action_kind,
                resource_id=resource.id,
                resource_version=resource.version_no,
                recipient_ref=token.recipient_ref,
                subject=f"询价：{resource.rfq_key}",
                body=resource.content_zh,
                payload_hash=resource.content_hash,
            )
        if token.action_kind == "first_buyer_contact":
            resource = require_row(
                self.session, MessageDraftRow, token.resource_id, "message draft"
            )
            eligibility = require_row(
                self.session,
                EligibilityDecisionRow,
                resource.eligibility_decision_id,
                "eligibility decision",
            )
            if eligibility.decision != "allow":
                raise ValueError("communication eligibility is no longer allow")
            suppression = self.session.scalar(
                select(SuppressionRow).where(
                    SuppressionRow.contact_id == resource.contact_id,
                    SuppressionRow.active.is_(True),
                    SuppressionRow.channel.in_([eligibility.channel, "all"]),
                )
            )
            if suppression is not None:
                raise ValueError("contact became suppressed after token issuance")
            return OutboundPayload(
                action_kind=token.action_kind,
                resource_id=resource.id,
                resource_version=resource.version_no,
                recipient_ref=token.recipient_ref,
                subject=resource.subject,
                body=resource.body,
                payload_hash=resource.content_hash,
            )
        raise ValueError(f"unsupported send action {token.action_kind}")
