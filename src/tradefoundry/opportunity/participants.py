from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.master.relations import RelationService
from tradefoundry.opportunity.contracts import ParticipantRole, ParticipantView
from tradefoundry.opportunity.models import (
    ParticipantCandidateRow,
    WorldEventRow,
    WorldEventSubjectRow,
)

DISCOVERY_VERSION = "relation-discovery-v1"

_DIRECT_ROLES = {
    "buyer": ParticipantRole.BUYER,
    "procuring_entity": ParticipantRole.BUYER,
    "owner": ParticipantRole.BUYER,
    "epc": ParticipantRole.EPC,
    "distributor": ParticipantRole.DISTRIBUTOR,
    "channel": ParticipantRole.DISTRIBUTOR,
    "supplier": ParticipantRole.SUPPLIER,
    "vendor": ParticipantRole.SUPPLIER,
    "awardee": ParticipantRole.AWARDEE,
    "winner": ParticipantRole.AWARDEE,
}
_RELATION_ROLES = {
    "buyer_for": ParticipantRole.BUYER,
    "purchaser_for": ParticipantRole.BUYER,
    "epc_for": ParticipantRole.EPC,
    "contractor_for": ParticipantRole.EPC,
    "distributor_for": ParticipantRole.DISTRIBUTOR,
    "channel_for": ParticipantRole.DISTRIBUTOR,
    "supplier_for": ParticipantRole.SUPPLIER,
    "vendor_for": ParticipantRole.SUPPLIER,
    "winner_for": ParticipantRole.AWARDEE,
    "awardee_for": ParticipantRole.AWARDEE,
}


class ParticipantDiscoveryService:
    def __init__(self, session: Session):
        self.session = session

    def discover(self, event_id: str) -> list[ParticipantView]:
        event = self.session.get(WorldEventRow, event_id)
        if event is None:
            raise LookupError(f"world event {event_id} not found")
        subjects = self.session.scalars(
            select(WorldEventSubjectRow).where(WorldEventSubjectRow.event_id == event_id)
        ).all()
        proposals: dict[tuple[str, str], dict] = {}
        for subject in subjects:
            direct_role = _DIRECT_ROLES.get(subject.role)
            if direct_role is not None:
                proposals[(subject.entity_id, direct_role.value)] = {
                    "confidence": event.reliability,
                    "distance": 0,
                    "basis": {
                        "kind": "event_subject",
                        "subject_role": subject.role,
                        "source_entity_id": subject.entity_id,
                    },
                    "claims": [subject.claim_id],
                }
            paths = RelationService(self.session).traverse(
                subject.entity_id, max_depth=3, as_of=event.occurred_at
            )
            for path in paths:
                final_step = path.steps[-1]
                role = _RELATION_ROLES.get(final_step.relation.relation_type)
                if role is None:
                    continue
                claims = [step.relation.evidence_claim_id for step in path.steps]
                confidence = event.reliability
                for step in path.steps:
                    confidence *= step.relation.confidence
                confidence *= 0.9 ** max(0, len(path.steps) - 1)
                key = (path.end_entity_id, role.value)
                proposal = {
                    "confidence": round(confidence, 6),
                    "distance": len(path.steps),
                    "basis": {
                        "kind": "relation_path",
                        "source_entity_id": subject.entity_id,
                        "relation_types": [step.relation.relation_type for step in path.steps],
                        "relation_ids": [step.relation.id for step in path.steps],
                    },
                    "claims": claims,
                }
                current = proposals.get(key)
                if current is None or proposal["confidence"] > current["confidence"]:
                    proposals[key] = proposal

        rows: list[ParticipantCandidateRow] = []
        for (entity_id, role), proposal in sorted(proposals.items()):
            existing = self.session.scalar(
                select(ParticipantCandidateRow).where(
                    ParticipantCandidateRow.event_id == event_id,
                    ParticipantCandidateRow.entity_id == entity_id,
                    ParticipantCandidateRow.role == role,
                    ParticipantCandidateRow.discovery_version == DISCOVERY_VERSION,
                )
            )
            if existing is not None:
                rows.append(existing)
                continue
            row = ParticipantCandidateRow(
                id=str(uuid4()),
                event_id=event_id,
                entity_id=entity_id,
                role=role,
                confidence=proposal["confidence"],
                hop_distance=proposal["distance"],
                basis_json=proposal["basis"],
                evidence_claim_ids_json=sorted(set(proposal["claims"])),
                discovery_version=DISCOVERY_VERSION,
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return [ParticipantView.model_validate(row) for row in rows]
