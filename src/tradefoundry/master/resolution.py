from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    DistinctRequest,
    MergeRequest,
    MergeView,
    SplitRequest,
)
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import (
    DistinctEntityPairRow,
    EntityRow,
    MergeCommandRow,
    SplitCommandRow,
)


class ResolutionService:
    def __init__(self, session: Session):
        self.session = session

    def merge(self, request: MergeRequest) -> MergeView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(MergeCommandRow).where(
                MergeCommandRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("merge idempotency key was reused with a different payload")
            return MergeView.model_validate(existing)
        winner = canonical_root(self.session, request.winner_entity_id)
        loser = canonical_root(self.session, request.loser_entity_id)
        if winner.id == loser.id:
            raise ValueError("entities already resolve to the same canonical entity")
        if winner.entity_type != loser.entity_type:
            raise ValueError("entities of different types cannot be merged")
        if winner.status == "frozen" or loser.status == "frozen":
            raise ValueError("frozen entities cannot be merged")
        if self.are_distinct(winner.id, loser.id):
            raise ValueError("entities are protected by an active distinct constraint")
        command = MergeCommandRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            winner_entity_id=winner.id,
            loser_entity_id=loser.id,
            decision_source=request.decision_source,
            score=request.score,
            features_json=request.features,
            actor=request.actor,
            reason=request.reason,
            status="applied",
        )
        loser.canonical_entity_id = winner.id
        loser.status = "merged"
        self.session.add(command)
        self.session.commit()
        return MergeView.model_validate(command)

    def split(self, entity_id: str, request: SplitRequest) -> SplitCommandRow:
        request_hash = payload_hash({"entity_id": entity_id, **request.model_dump(mode="json")})
        existing = self.session.scalar(
            select(SplitCommandRow).where(
                SplitCommandRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("split idempotency key was reused with a different payload")
            return existing
        entity = self.session.get(EntityRow, entity_id)
        if entity is None:
            raise LookupError(f"entity {entity_id} not found")
        if entity.canonical_entity_id is None:
            raise ValueError("entity is not directly merged and cannot be split")
        row = SplitCommandRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            entity_id=entity.id,
            previous_canonical_entity_id=entity.canonical_entity_id,
            actor=request.actor,
            reason=request.reason,
        )
        entity.canonical_entity_id = None
        entity.status = "active"
        self.session.add(row)
        self.session.commit()
        return row

    def undo_merge(self, command_id: str, *, actor: str, reason: str) -> MergeView:
        command = self.session.get(MergeCommandRow, command_id)
        if command is None:
            raise LookupError(f"merge command {command_id} not found")
        if command.status == "undone":
            return MergeView.model_validate(command)
        loser = self.session.get(EntityRow, command.loser_entity_id)
        if loser is None or loser.canonical_entity_id != command.winner_entity_id:
            raise ValueError("merge can no longer be undone directly; split the entity explicitly")
        loser.canonical_entity_id = None
        loser.status = "active"
        command.status = "undone"
        command.undone_at = datetime.now(UTC)
        command.features_json = {
            **command.features_json,
            "undo_actor": actor,
            "undo_reason": reason,
        }
        self.session.commit()
        return MergeView.model_validate(command)

    def mark_distinct(self, request: DistinctRequest) -> DistinctEntityPairRow:
        left = canonical_root(self.session, request.left_entity_id)
        right = canonical_root(self.session, request.right_entity_id)
        if left.id == right.id:
            raise ValueError("split merged entities before marking them distinct")
        left_id, right_id = sorted((left.id, right.id))
        existing = self.session.scalar(
            select(DistinctEntityPairRow).where(
                DistinctEntityPairRow.left_entity_id == left_id,
                DistinctEntityPairRow.right_entity_id == right_id,
            )
        )
        if existing is not None:
            return existing
        row = DistinctEntityPairRow(
            id=str(uuid4()),
            left_entity_id=left_id,
            right_entity_id=right_id,
            actor=request.actor,
            reason=request.reason,
            active=True,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def are_distinct(self, left_id: str, right_id: str) -> bool:
        left, right = sorted((left_id, right_id))
        return (
            self.session.scalar(
                select(DistinctEntityPairRow).where(
                    DistinctEntityPairRow.active.is_(True),
                    DistinctEntityPairRow.left_entity_id == left,
                    DistinctEntityPairRow.right_entity_id == right,
                )
            )
            is not None
        )
