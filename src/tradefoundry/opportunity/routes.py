from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.opportunity.contracts import RouteType, RouteView
from tradefoundry.opportunity.models import (
    EventSignalRow,
    ParticipantCandidateRow,
    RouteCandidateRow,
    WorldEventRow,
)

GENERATOR_VERSION = "deal-route-v1"


class RouteCandidateService:
    def __init__(self, session: Session):
        self.session = session

    def generate(self, event_id: str) -> list[RouteView]:
        if self.session.get(WorldEventRow, event_id) is None:
            raise LookupError(f"world event {event_id} not found")
        participants = self.session.scalars(
            select(ParticipantCandidateRow).where(ParticipantCandidateRow.event_id == event_id)
        ).all()
        signals = self.session.scalars(
            select(EventSignalRow).where(EventSignalRow.event_id == event_id)
        ).all()
        by_role: dict[str, list[ParticipantCandidateRow]] = {}
        for participant in participants:
            by_role.setdefault(participant.role, []).append(participant)
        signal_types = {signal.signal_type for signal in signals}
        input_snapshot = {
            "participants": sorted(
                [
                    {
                        "id": row.id,
                        "role": row.role,
                        "confidence": row.confidence,
                    }
                    for row in participants
                ],
                key=payload_hash,
            ),
            "signals": sorted(signal_types),
        }
        input_hash = payload_hash(input_snapshot)

        specifications = {
            RouteType.DIRECT_BID: self._spec(
                by_role.get("buyer", []),
                "explicit_rfq" in signal_types,
                "A verified buyer and explicit RFQ signal support direct bidding.",
                ["verified buyer", "explicit RFQ"],
            ),
            RouteType.PRE_AWARD_SUPPLY: self._spec(
                by_role.get("epc", []),
                bool(signal_types.intersection({"project_approval", "expansion", "explicit_rfq"})),
                "An EPC candidate can be approached before award, subject to later "
                "policy approval.",
                ["EPC candidate", "pre-award project signal"],
            ),
            RouteType.POST_AWARD_SUPPLY: self._spec(
                by_role.get("awardee", []),
                "award" in signal_types,
                "An evidence-backed awardee supports a post-award supply route.",
                ["awardee candidate", "award signal"],
            ),
            RouteType.CHANNEL: self._spec(
                by_role.get("distributor", []),
                True,
                "An evidence-backed distributor supports a channel route.",
                ["distributor candidate"],
            ),
        }
        rows: list[RouteCandidateRow] = []
        for route_type, spec in specifications.items():
            existing = self.session.scalar(
                select(RouteCandidateRow).where(
                    RouteCandidateRow.event_id == event_id,
                    RouteCandidateRow.route_type == route_type.value,
                    RouteCandidateRow.generator_version == GENERATOR_VERSION,
                    RouteCandidateRow.input_hash == input_hash,
                )
            )
            if existing is not None:
                rows.append(existing)
                continue
            row = RouteCandidateRow(
                id=str(uuid4()),
                event_id=event_id,
                route_type=route_type.value,
                feasibility="feasible" if not spec["missing"] else "excluded",
                participant_candidate_ids_json=spec["participant_ids"],
                reasons_json=[spec["reason"]]
                if not spec["missing"]
                else [
                    "Excluded because required evidence is missing: " + ", ".join(spec["missing"])
                ],
                missing_requirements_json=spec["missing"],
                generator_version=GENERATOR_VERSION,
                input_hash=input_hash,
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return [RouteView.model_validate(row) for row in rows]

    @staticmethod
    def _spec(
        participants: list[ParticipantCandidateRow],
        condition: bool,
        success_reason: str,
        requirement_labels: list[str],
    ) -> dict:
        missing: list[str] = []
        if not participants:
            missing.append(requirement_labels[0])
        if len(requirement_labels) > 1 and not condition:
            missing.append(requirement_labels[1])
        return {
            "participant_ids": sorted(row.id for row in participants),
            "reason": success_reason,
            "missing": missing,
        }
