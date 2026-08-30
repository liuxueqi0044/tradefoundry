from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow, ConflictGroupRow


class ConflictService:
    def __init__(self, session: Session):
        self.session = session

    def detect(self, claim: ClaimRow) -> ConflictGroupRow | None:
        candidates = self.session.scalars(
            select(ClaimRow).where(
                ClaimRow.id != claim.id,
                ClaimRow.subject_key == claim.subject_key,
                ClaimRow.field_path == claim.field_path,
                ClaimRow.status.not_in(["rejected", "corrected"]),
            )
        ).all()
        conflicting = [
            item
            for item in candidates
            if item.normalized_value_json != claim.normalized_value_json
            and self._overlaps(item, claim)
        ]
        if not conflicting:
            return None
        group = next(
            (
                self.session.get(ConflictGroupRow, item.conflict_group_id)
                for item in conflicting
                if item.conflict_group_id
            ),
            None,
        )
        if group is None:
            group = ConflictGroupRow(
                id=str(uuid4()), subject_key=claim.subject_key, field_path=claim.field_path
            )
            self.session.add(group)
            self.session.flush()
        claim.conflict_group_id = group.id
        claim.status = "conflict"
        for item in conflicting:
            item.conflict_group_id = group.id
            item.status = "conflict"
        return group

    def as_of(self, subject_key: str, at: datetime) -> list[ClaimRow]:
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        rows = self.session.scalars(
            select(ClaimRow)
            .where(
                ClaimRow.subject_key == subject_key,
                ClaimRow.status.not_in(["rejected", "corrected"]),
            )
            .order_by(ClaimRow.observed_at.desc())
        ).all()
        return [
            row
            for row in rows
            if (row.valid_from is None or self._aware(row.valid_from) <= at)
            and (row.valid_to is None or at < self._aware(row.valid_to))
        ]

    @classmethod
    def _overlaps(cls, left: ClaimRow, right: ClaimRow) -> bool:
        minimum = datetime.min.replace(tzinfo=UTC)
        maximum = datetime.max.replace(tzinfo=UTC)
        left_start = cls._aware(left.valid_from) if left.valid_from else minimum
        right_start = cls._aware(right.valid_from) if right.valid_from else minimum
        left_end = cls._aware(left.valid_to) if left.valid_to else maximum
        right_end = cls._aware(right.valid_to) if right.valid_to else maximum
        return left_start < right_end and right_start < left_end

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
