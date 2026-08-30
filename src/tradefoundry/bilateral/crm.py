from __future__ import annotations

import re

import phonenumbers
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import (
    BuyerProfileCreate,
    ContactBundle,
    ContactCreate,
    EligibilityRequest,
    SuppressionCreate,
)
from tradefoundry.bilateral.models import (
    BuyerProfileRow,
    ContactAffiliationRow,
    ContactPointRow,
    ContactRow,
    EligibilityDecisionRow,
    SuppressionRow,
)
from tradefoundry.bilateral.ports import PolicyDecisionPort
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.master.models import EntityRow

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class BuyerCrmService:
    def __init__(self, session: Session):
        self.session = session

    def create_buyer(self, request: BuyerProfileCreate) -> BuyerProfileRow:
        request_hash = request_fingerprint({"operation": "buyer_profile.create"}, request)
        existing = idempotent_row(
            self.session, BuyerProfileRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        entity = require_row(self.session, EntityRow, request.entity_id, "entity")
        if entity.status != "active" or entity.canonical_entity_id is not None:
            raise ValueError("buyer must reference an active canonical Entity")
        if entity.entity_type not in {"organization", "company", "public_body"}:
            raise ValueError("buyer Entity must represent an organization")
        if self.session.scalar(
            select(BuyerProfileRow).where(BuyerProfileRow.entity_id == request.entity_id)
        ):
            raise ValueError("buyer profile already exists for this Entity")
        for claim_id in request.evidence_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "evidence Claim")
        row = BuyerProfileRow(
            id=new_id(),
            entity_id=request.entity_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            attributes_json=request.attributes,
            evidence_claim_ids_json=request.evidence_claim_ids,
            review_status=request.review_status.value,
            status="active",
        )
        self.session.add(row)
        self.session.commit()
        return row

    def create_contact(self, request: ContactCreate) -> ContactRow:
        request_hash = request_fingerprint({"operation": "contact.create"}, request)
        existing = idempotent_row(self.session, ContactRow, request.idempotency_key, request_hash)
        if existing is not None:
            return existing
        if self.session.scalar(
            select(ContactRow).where(ContactRow.contact_key == request.contact_key)
        ):
            raise ValueError("contact_key already exists")
        for item in request.contact_points:
            require_row(self.session, ClaimRow, item.source_claim_id, "contact source Claim")
        for item in request.affiliations:
            require_row(self.session, BuyerProfileRow, item.buyer_profile_id, "buyer profile")
            require_row(self.session, ClaimRow, item.source_claim_id, "role source Claim")
            if item.valid_to is not None and item.valid_to <= item.valid_from:
                raise ValueError("contact affiliation valid_to must be after valid_from")
        row = ContactRow(
            id=new_id(),
            contact_key=request.contact_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            display_name=request.display_name,
            status="active",
        )
        self.session.add(row)
        self.session.flush()
        self.session.add_all(
            [
                ContactPointRow(
                    id=new_id(),
                    contact_id=row.id,
                    channel=item.channel,
                    raw_value=item.value,
                    normalized_value=_normalize_contact_point(
                        item.channel, item.value, item.jurisdiction
                    ),
                    source_claim_id=item.source_claim_id,
                    lawful_basis=item.lawful_basis,
                    jurisdiction=item.jurisdiction,
                    status="active",
                    captured_at=item.captured_at,
                )
                for item in request.contact_points
            ]
        )
        self.session.add_all(
            [
                ContactAffiliationRow(
                    id=new_id(),
                    contact_id=row.id,
                    buyer_profile_id=item.buyer_profile_id,
                    role=item.role,
                    source_claim_id=item.source_claim_id,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                )
                for item in request.affiliations
            ]
        )
        self.session.commit()
        return row

    def get_contact(self, contact_id: str) -> ContactBundle:
        contact = require_row(self.session, ContactRow, contact_id, "contact")
        points = self.session.scalars(
            select(ContactPointRow)
            .where(ContactPointRow.contact_id == contact_id)
            .order_by(ContactPointRow.created_at, ContactPointRow.id)
        ).all()
        affiliations = self.session.scalars(
            select(ContactAffiliationRow)
            .where(ContactAffiliationRow.contact_id == contact_id)
            .order_by(ContactAffiliationRow.valid_from, ContactAffiliationRow.id)
        ).all()
        return ContactBundle(
            contact=contact,
            contact_points=[
                {
                    "id": item.id,
                    "channel": item.channel,
                    "value": item.raw_value,
                    "normalized_value": item.normalized_value,
                    "source_claim_id": item.source_claim_id,
                    "lawful_basis": item.lawful_basis,
                    "jurisdiction": item.jurisdiction,
                    "status": item.status,
                    "captured_at": item.captured_at,
                }
                for item in points
            ],
            affiliations=[
                {
                    "id": item.id,
                    "buyer_profile_id": item.buyer_profile_id,
                    "role": item.role,
                    "source_claim_id": item.source_claim_id,
                    "valid_from": item.valid_from,
                    "valid_to": item.valid_to,
                }
                for item in affiliations
            ],
        )


class CommunicationEligibilityService:
    def __init__(self, session: Session, policy: PolicyDecisionPort):
        self.session = session
        self.policy = policy

    def suppress(self, contact_id: str, request: SuppressionCreate) -> SuppressionRow:
        require_row(self.session, ContactRow, contact_id, "contact")
        request_hash = request_fingerprint(
            {"operation": "contact.suppress", "contact_id": contact_id}, request
        )
        existing = idempotent_row(
            self.session, SuppressionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        row = SuppressionRow(
            id=new_id(),
            contact_id=contact_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            channel=request.channel,
            reason=request.reason,
            source_ref=request.source_ref,
            active=True,
            occurred_at=request.occurred_at,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def evaluate(self, contact_id: str, request: EligibilityRequest) -> EligibilityDecisionRow:
        contact = require_row(self.session, ContactRow, contact_id, "contact")
        request_hash = request_fingerprint(
            {"operation": "contact.eligibility", "contact_id": contact_id}, request
        )
        existing = idempotent_row(
            self.session, EligibilityDecisionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        blockers: list[str] = []
        active_suppressions = self.session.scalars(
            select(SuppressionRow).where(
                SuppressionRow.contact_id == contact_id,
                SuppressionRow.active.is_(True),
                SuppressionRow.channel.in_([request.channel, "all"]),
            )
        ).all()
        if active_suppressions:
            blockers.extend(f"suppression:{item.reason}:{item.id}" for item in active_suppressions)
        contact_point = self.session.scalar(
            select(ContactPointRow).where(
                ContactPointRow.contact_id == contact_id,
                ContactPointRow.channel == request.channel,
                ContactPointRow.jurisdiction == request.jurisdiction,
                ContactPointRow.status == "active",
            )
        )
        if contact.status != "active":
            blockers.append("contact_inactive")
        if contact_point is None:
            blockers.append("no_active_contact_point_for_channel_and_jurisdiction")
        elif not contact_point.lawful_basis:
            blockers.append("lawful_basis_missing")

        if blockers:
            decision = "deny"
            policy_ref = "safety:suppression-and-contact-point-v1"
            policy_version = "local-non-bypassable-v1"
        else:
            policy = self.policy.communication_eligibility(contact_id=contact_id, request=request)
            policy_ref = policy.policy_decision_ref
            policy_version = policy.policy_version
            blockers.extend(policy.reasons)
            decision = {
                "allow": "allow",
                "deny": "deny",
                "require_approval": "review_required",
            }[policy.decision]
        row = EligibilityDecisionRow(
            id=new_id(),
            contact_id=contact_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            channel=request.channel,
            jurisdiction=request.jurisdiction,
            decision=decision,
            blockers_json=blockers,
            policy_decision_ref=policy_ref,
            policy_version=policy_version,
            evaluated_at=request.evaluated_at,
        )
        self.session.add(row)
        self.session.commit()
        return row


def _normalize_contact_point(channel: str, value: str, jurisdiction: str) -> str:
    if channel == "email":
        normalized = value.strip().casefold()
        if not EMAIL_RE.fullmatch(normalized):
            raise ValueError("invalid email contact point")
        return normalized
    try:
        parsed = phonenumbers.parse(value, jurisdiction)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("invalid phone contact point") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("invalid phone contact point")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
