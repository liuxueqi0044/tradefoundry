from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    RelationCreate,
    RelationPath,
    RelationStep,
    RelationView,
)
from tradefoundry.master.evidence import require_reliable_claim
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import EntityRow, RelationRow


class RelationService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: RelationCreate) -> RelationView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        for entity_id in (request.subject_entity_id, request.object_entity_id):
            if self.session.get(EntityRow, entity_id) is None:
                raise LookupError(f"entity {entity_id} not found")
        claim = require_reliable_claim(self.session, request.evidence_claim_id)
        if request.review_status == "verified" and claim.status != "verified":
            raise ValueError("a verified relation requires a verified evidence Claim")
        existing = self.session.scalar(
            select(RelationRow).where(
                RelationRow.subject_entity_id == request.subject_entity_id,
                RelationRow.relation_type == request.relation_type,
                RelationRow.object_entity_id == request.object_entity_id,
                RelationRow.evidence_claim_id == request.evidence_claim_id,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("relation identity was reused with a different payload")
            return RelationView.model_validate(existing)
        row = RelationRow(
            id=str(uuid4()),
            request_hash=request_hash,
            subject_entity_id=request.subject_entity_id,
            relation_type=request.relation_type,
            object_entity_id=request.object_entity_id,
            evidence_claim_id=request.evidence_claim_id,
            confidence=request.confidence,
            review_status=request.review_status,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
        )
        self.session.add(row)
        self.session.commit()
        return RelationView.model_validate(row)

    def traverse(
        self,
        entity_id: str,
        *,
        max_depth: int = 3,
        as_of: datetime | None = None,
        direction: str = "both",
    ) -> list[RelationPath]:
        if not 1 <= max_depth <= 3:
            raise ValueError("max_depth must be between 1 and 3")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming or both")
        start = canonical_root(self.session, entity_id).id
        at = as_of or datetime.now(UTC)
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        relations = [
            row for row in self.session.scalars(select(RelationRow)).all() if self._active(row, at)
        ]
        paths: list[RelationPath] = []
        queue: list[tuple[str, list[RelationStep], set[str]]] = [(start, [], {start})]
        while queue:
            current, steps, visited = queue.pop(0)
            if len(steps) >= max_depth:
                continue
            for relation in relations:
                subject = canonical_root(self.session, relation.subject_entity_id).id
                object_ = canonical_root(self.session, relation.object_entity_id).id
                next_id: str | None = None
                if direction in {"outgoing", "both"} and subject == current:
                    next_id = object_
                elif direction in {"incoming", "both"} and object_ == current:
                    next_id = subject
                if next_id is None or next_id in visited:
                    continue
                step = RelationStep(
                    relation=RelationView.model_validate(relation),
                    from_entity_id=current,
                    to_entity_id=next_id,
                    depth=len(steps) + 1,
                )
                next_steps = [*steps, step]
                paths.append(
                    RelationPath(start_entity_id=start, end_entity_id=next_id, steps=next_steps)
                )
                queue.append((next_id, next_steps, visited | {next_id}))
        return paths

    @staticmethod
    def _active(row: RelationRow, at: datetime) -> bool:
        valid_from = row.valid_from
        valid_to = row.valid_to
        if valid_from and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=UTC)
        if valid_to and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=UTC)
        return (valid_from is None or valid_from <= at) and (valid_to is None or at < valid_to)
