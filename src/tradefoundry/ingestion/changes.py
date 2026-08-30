from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tradefoundry.ingestion.contracts import ChangeType, SourceRecordCandidate
from tradefoundry.ingestion.models import SourceRecordRow


@dataclass(frozen=True)
class DetectedChange:
    change_type: ChangeType
    details: dict


class ChangeDetector:
    def detect(
        self, previous: SourceRecordRow | None, current: SourceRecordCandidate, new_hash: str
    ) -> list[DetectedChange]:
        if previous is None:
            return [DetectedChange(ChangeType.ADDED, {})]
        if previous.payload_hash == new_hash:
            return []

        changes: list[DetectedChange] = []
        if current.revoked and not previous.revoked:
            changes.append(DetectedChange(ChangeType.REVOKED, {}))
        if not self._same_time(previous.deadline, current.deadline):
            changes.append(
                DetectedChange(
                    ChangeType.DEADLINE_CHANGED,
                    {
                        "old": previous.deadline.isoformat() if previous.deadline else None,
                        "new": current.deadline.isoformat() if current.deadline else None,
                    },
                )
            )
        old_attachments = sorted(previous.attachment_hashes or [])
        new_attachments = sorted(current.attachment_hashes)
        if old_attachments != new_attachments:
            changes.append(
                DetectedChange(
                    ChangeType.ATTACHMENT_CHANGED,
                    {"old": old_attachments, "new": new_attachments},
                )
            )
        if not changes:
            changes.append(DetectedChange(ChangeType.UPDATED, {}))
        return changes

    @staticmethod
    def _same_time(left: datetime | None, right: datetime | None) -> bool:
        if left is None or right is None:
            return left is right
        return left.isoformat() == right.isoformat()
