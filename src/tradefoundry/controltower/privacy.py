from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.models import ContactPointRow, ContactRow, SuppressionRow
from tradefoundry.controltower.common import (
    aware,
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.controltower.contracts import (
    CommunicationEvaluate,
    PolicyDecisionCreate,
)
from tradefoundry.controltower.models import CommunicationDecisionRow
from tradefoundry.controltower.policy import PolicyEngine


class CommunicationPolicyService:
    """Builds authoritative contact context, then delegates every rule to Policy Engine."""

    def __init__(self, session: Session, policy_engine: PolicyEngine | None = None):
        self.session = session
        self.policy = policy_engine or PolicyEngine(session)

    def evaluate(self, request: CommunicationEvaluate) -> CommunicationDecisionRow:
        request_hash = request_fingerprint({"operation": "risk.communication.evaluate"}, request)
        existing = idempotent_row(
            self.session, CommunicationDecisionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        contact = require_row(self.session, ContactRow, request.contact_id, "contact")
        point = self.session.scalar(
            select(ContactPointRow)
            .where(
                ContactPointRow.contact_id == contact.id,
                ContactPointRow.channel == request.channel,
                ContactPointRow.status == "active",
            )
            .order_by(ContactPointRow.created_at.desc())
        )
        suppressions = list(
            self.session.scalars(
                select(SuppressionRow).where(
                    SuppressionRow.contact_id == contact.id,
                    SuppressionRow.active.is_(True),
                    SuppressionRow.channel.in_([request.channel, "all"]),
                )
            )
        )
        authoritative_basis = point.lawful_basis if point else None
        point_jurisdiction = point.jurisdiction if point else None
        basis_mismatch = bool(
            request.lawful_basis
            and authoritative_basis
            and request.lawful_basis != authoritative_basis
        )
        retention_expired = bool(
            request.retention_deadline and aware(request.retention_deadline) <= aware(request.as_of)
        )
        context = {
            "contact_active": contact.status == "active",
            "contact_point_present": point is not None,
            "channel": request.channel,
            "jurisdiction": request.jurisdiction.upper(),
            "point_jurisdiction": point_jurisdiction,
            "jurisdiction_matches": point_jurisdiction == request.jurisdiction.upper(),
            "purpose": request.purpose,
            "lawful_basis": authoritative_basis,
            "lawful_basis_present": bool(authoritative_basis),
            "lawful_basis_mismatch": basis_mismatch,
            "suppressed": bool(suppressions),
            "retention_expired": retention_expired,
            "first_contact": request.first_contact,
            "as_of": aware(request.as_of).isoformat(),
        }
        decision = self.policy.decide(
            PolicyDecisionCreate(
                bundle_key=request.bundle_key,
                idempotency_key=f"{request.idempotency_key}:policy",
                actor=request.actor,
                actor_roles=request.actor_roles,
                action="communicate",
                resource_type="contact",
                resource_id=contact.id,
                context=context,
            )
        )
        blockers = list(decision.reasons_json) if decision.decision != "allow" else []
        row = CommunicationDecisionRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            contact_id=contact.id,
            policy_decision_id=decision.id,
            channel=request.channel,
            jurisdiction=request.jurisdiction.upper(),
            purpose=request.purpose,
            suppression_ids_json=[value.id for value in suppressions],
            lawful_basis=authoritative_basis,
            retention_deadline=request.retention_deadline,
            decision=decision.decision,
            blockers_json=blockers,
        )
        self.session.add(row)
        self.session.commit()
        return row
