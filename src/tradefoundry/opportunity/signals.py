from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow
from tradefoundry.opportunity.contracts import SignalType, SignalView
from tradefoundry.opportunity.models import EventSignalRow, WorldEventClaimRow, WorldEventRow

CLASSIFIER_VERSION = "deterministic-signal-v1"

_EVENT_SIGNAL = {
    "rfq": SignalType.EXPLICIT_RFQ,
    "project_approval": SignalType.PROJECT_APPROVAL,
    "award": SignalType.AWARD,
    "expansion": SignalType.EXPANSION,
    "regulatory_change": SignalType.REGULATORY_CHANGE,
    "supply_disruption": SignalType.SUPPLY_DISRUPTION,
}
_KEYWORDS = {
    SignalType.EXPLICIT_RFQ: ("rfq", "request for quotation", "询价", "招标"),
    SignalType.PROJECT_APPROVAL: ("approved", "approval", "批准", "立项"),
    SignalType.AWARD: ("award", "awarded", "中标", "授标"),
    SignalType.EXPANSION: ("expansion", "expand", "扩建", "扩产"),
    SignalType.REGULATORY_CHANGE: ("regulation", "regulatory", "法规", "标准变更"),
    SignalType.SUPPLY_DISRUPTION: ("disruption", "shortage", "中断", "短缺"),
}
_PRIORITY = {
    SignalType.EXPLICIT_RFQ: 100,
    SignalType.SUPPLY_DISRUPTION: 90,
    SignalType.REGULATORY_CHANGE: 80,
    SignalType.AWARD: 70,
    SignalType.EXPANSION: 65,
    SignalType.PROJECT_APPROVAL: 60,
    SignalType.OTHER: 10,
}


class SignalClassifier:
    def __init__(self, session: Session):
        self.session = session

    def classify(self, event_id: str) -> list[SignalView]:
        event = self.session.get(WorldEventRow, event_id)
        if event is None:
            raise LookupError(f"world event {event_id} not found")
        claim_ids = self.session.scalars(
            select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event_id)
        ).all()
        claims = [self.session.get(ClaimRow, claim_id) for claim_id in claim_ids]
        corpus = " ".join(
            [event.title, event.event_type]
            + [f"{claim.field_path} {claim.value_json}" for claim in claims if claim is not None]
        ).casefold()
        matches: dict[SignalType, list[str]] = {}
        primary = _EVENT_SIGNAL.get(event.event_type)
        if primary is not None:
            matches.setdefault(primary, []).append(f"event_type={event.event_type}")
        for signal_type, keywords in _KEYWORDS.items():
            found = [keyword for keyword in keywords if keyword.casefold() in corpus]
            if found:
                matches.setdefault(signal_type, []).extend(f"keyword={word}" for word in found)
        if not matches:
            matches[SignalType.OTHER] = ["no configured signal pattern matched"]

        rows: list[EventSignalRow] = []
        for signal_type, basis in matches.items():
            existing = self.session.scalar(
                select(EventSignalRow).where(
                    EventSignalRow.event_id == event_id,
                    EventSignalRow.signal_type == signal_type.value,
                    EventSignalRow.classifier_version == CLASSIFIER_VERSION,
                )
            )
            if existing is not None:
                rows.append(existing)
                continue
            confidence = min(1.0, event.reliability * (1.0 if primary == signal_type else 0.9))
            row = EventSignalRow(
                id=str(uuid4()),
                event_id=event_id,
                signal_type=signal_type.value,
                priority=_PRIORITY[signal_type],
                confidence=confidence,
                basis_json={"matches": sorted(set(basis)), "claim_ids": sorted(claim_ids)},
                classifier_version=CLASSIFIER_VERSION,
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return [
            SignalView.model_validate(row)
            for row in sorted(rows, key=lambda value: value.priority, reverse=True)
        ]
