from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from stdnum import lei
from stdnum.eu import vat as eu_vat

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    DistinctRequest,
    IdentifierCreate,
    IdentifierResolutionResult,
    IdentifierView,
    IdentityConflictReviewRequest,
    IdentityConflictView,
    MergeRequest,
)
from tradefoundry.master.evidence import require_reliable_claim
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import (
    DistinctEntityPairRow,
    EntityIdentifierRow,
    EntityRow,
    IdentityConflictRow,
)
from tradefoundry.master.normalization import MasterDataNormalizer
from tradefoundry.master.resolution import ResolutionService


class IdentifierResolutionService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = MasterDataNormalizer()
        self.resolution = ResolutionService(session)

    def add(self, entity_id: str, request: IdentifierCreate) -> IdentifierResolutionResult:
        entity = self.session.get(EntityRow, entity_id)
        if entity is None:
            raise LookupError(f"entity {entity_id} not found")
        require_reliable_claim(self.session, request.source_claim_id)
        scheme = request.scheme.lower()
        normalized = self.normalize(scheme, request.value)
        existing_same_entity = self.session.scalar(
            select(EntityIdentifierRow).where(
                EntityIdentifierRow.entity_id == entity.id,
                EntityIdentifierRow.scheme == scheme,
                EntityIdentifierRow.normalized_value == normalized,
                EntityIdentifierRow.source_claim_id == request.source_claim_id,
            )
        )
        if existing_same_entity is not None:
            if existing_same_entity.strength != request.strength:
                raise ValueError("identifier was reused with a different strength")
            return IdentifierResolutionResult(
                identifier=IdentifierView.model_validate(existing_same_entity),
                canonical_entity_id=canonical_root(self.session, entity.id).id,
                outcome="idempotent",
            )
        identifier = EntityIdentifierRow(
            id=str(uuid4()),
            entity_id=entity.id,
            scheme=scheme,
            raw_value=request.value,
            normalized_value=normalized,
            strength=request.strength,
            status="active",
            source_claim_id=request.source_claim_id,
        )
        self.session.add(identifier)
        self.session.commit()
        if request.strength != "strong":
            return self._result(identifier, "recorded_weak")

        matches = self.session.scalars(
            select(EntityIdentifierRow).where(
                EntityIdentifierRow.id != identifier.id,
                EntityIdentifierRow.scheme == scheme,
                EntityIdentifierRow.normalized_value == normalized,
                EntityIdentifierRow.strength == "strong",
            )
        ).all()
        merge_id: str | None = None
        for match in matches:
            current_root = canonical_root(self.session, entity.id)
            other_root = canonical_root(self.session, match.entity_id)
            if current_root.id == other_root.id:
                continue
            conflict_reason = self._conflict_reason(current_root, other_root)
            if conflict_reason:
                conflict = self._freeze_conflict(
                    identifier, match, current_root, other_root, conflict_reason
                )
                return self._result(
                    identifier,
                    "frozen_conflict",
                    conflict_id=conflict.id,
                )
            winner, loser = sorted(
                (current_root, other_root), key=lambda value: (value.created_at, value.id)
            )
            command = self.resolution.merge(
                MergeRequest(
                    winner_entity_id=winner.id,
                    loser_entity_id=loser.id,
                    idempotency_key=(
                        "strong:"
                        + payload_hash(
                            {
                                "scheme": scheme,
                                "value": normalized,
                                "entities": sorted((winner.id, loser.id)),
                            }
                        )
                    ),
                    decision_source="strong_identifier",
                    actor="system:identifier-resolver",
                    reason=f"exact strong identifier match on {scheme}",
                    score=1.0,
                    features={"scheme": scheme, "normalized_value": normalized},
                )
            )
            merge_id = command.id
        outcome = "auto_merged" if merge_id else "recorded_unique"
        return self._result(identifier, outcome, merge_command_id=merge_id)

    def normalize(self, scheme: str, value: str) -> str:
        if scheme == "lei":
            normalized = lei.compact(value)
            if not lei.is_valid(normalized):
                raise ValueError("invalid LEI checksum or format")
            return normalized
        if scheme == "eu_vat":
            normalized = eu_vat.compact(value)
            if not eu_vat.is_valid(normalized):
                raise ValueError("invalid EU VAT identifier")
            return normalized
        if scheme == "domain":
            return self.normalizer.normalize_domain(value)
        if scheme == "email":
            return self.normalizer.normalize_email(value)
        if scheme.startswith("phone"):
            region = scheme.partition(":")[2].upper() or None
            return self.normalizer.normalize_phone(value, region)
        if scheme.startswith(("vat", "registration", "tax")):
            normalized = re.sub(r"[^0-9A-Za-z]", "", value).upper()
            if len(normalized) < 3:
                raise ValueError(f"invalid {scheme} identifier")
            return normalized
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("identifier becomes empty after normalization")
        return normalized

    def review_conflict(
        self, conflict_id: str, request: IdentityConflictReviewRequest
    ) -> IdentityConflictView:
        conflict = self.session.get(IdentityConflictRow, conflict_id)
        if conflict is None:
            raise LookupError(f"identity conflict {conflict_id} not found")
        if conflict.status != "open":
            return IdentityConflictView.model_validate(conflict)
        left = canonical_root(self.session, conflict.left_entity_id)
        right = canonical_root(self.session, conflict.right_entity_id)
        if request.action == "keep_distinct":
            self.resolution.mark_distinct(
                DistinctRequest(
                    left_entity_id=left.id,
                    right_entity_id=right.id,
                    actor=request.reviewer,
                    reason=request.reason,
                )
            )
            conflict.status = "resolved_distinct"
        else:
            if left.entity_type != right.entity_type:
                raise ValueError("incompatible entity types cannot be merged")
            pairs = self.session.scalars(
                select(DistinctEntityPairRow).where(
                    DistinctEntityPairRow.active.is_(True),
                    DistinctEntityPairRow.left_entity_id == min(left.id, right.id),
                    DistinctEntityPairRow.right_entity_id == max(left.id, right.id),
                )
            ).all()
            for pair in pairs:
                pair.active = False
            for entity in (left, right):
                entity.status = "active"
                entity.frozen_reason = None
            self.session.flush()
            older, newer = sorted((left, right), key=lambda item: (item.created_at, item.id))
            command = self.resolution.merge(
                MergeRequest(
                    winner_entity_id=older.id,
                    loser_entity_id=newer.id,
                    idempotency_key=f"identity-conflict:{conflict.id}",
                    decision_source="human_identity_review",
                    actor=request.reviewer,
                    reason=request.reason,
                    score=1.0,
                    features={
                        "scheme": conflict.scheme,
                        "normalized_value": conflict.normalized_value,
                    },
                )
            )
            conflict.status = "resolved_merged"
            conflict.resolution_json = {"merge_command_id": command.id}
        if request.action == "keep_distinct":
            for entity in (left, right):
                entity.status = "active"
                entity.frozen_reason = None
        identifiers = self.session.scalars(
            select(EntityIdentifierRow).where(
                EntityIdentifierRow.scheme == conflict.scheme,
                EntityIdentifierRow.normalized_value == conflict.normalized_value,
                EntityIdentifierRow.entity_id.in_((left.id, right.id)),
            )
        ).all()
        for identifier in identifiers:
            identifier.status = "active" if request.action == "merge" else "conflicted_confirmed"
        conflict.resolution_json = {
            **(conflict.resolution_json or {}),
            "action": request.action,
            "reviewer": request.reviewer,
            "reason": request.reason,
        }
        self.session.commit()
        return IdentityConflictView.model_validate(conflict)

    def _conflict_reason(self, left: EntityRow, right: EntityRow) -> str | None:
        if left.entity_type != right.entity_type:
            return "strong identifier is attached to incompatible entity types"
        if left.status == "frozen" or right.status == "frozen":
            return "strong identifier touches an already frozen entity"
        if self.resolution.are_distinct(left.id, right.id):
            return "strong identifier contradicts a human distinct constraint"
        return None

    def _freeze_conflict(
        self,
        identifier: EntityIdentifierRow,
        match: EntityIdentifierRow,
        left: EntityRow,
        right: EntityRow,
        reason: str,
    ) -> IdentityConflictRow:
        left_id, right_id = sorted((left.id, right.id))
        existing = self.session.scalar(
            select(IdentityConflictRow).where(
                IdentityConflictRow.scheme == identifier.scheme,
                IdentityConflictRow.normalized_value == identifier.normalized_value,
                IdentityConflictRow.left_entity_id == left_id,
                IdentityConflictRow.right_entity_id == right_id,
            )
        )
        if existing is None:
            existing = IdentityConflictRow(
                id=str(uuid4()),
                scheme=identifier.scheme,
                normalized_value=identifier.normalized_value,
                left_entity_id=left_id,
                right_entity_id=right_id,
                reason=reason,
                status="open",
            )
            self.session.add(existing)
        identifier.status = "conflicted"
        match.status = "conflicted"
        for entity in (left, right):
            entity.status = "frozen"
            entity.frozen_reason = reason
        self.session.commit()
        return existing

    def _result(
        self,
        identifier: EntityIdentifierRow,
        outcome: str,
        *,
        merge_command_id: str | None = None,
        conflict_id: str | None = None,
    ) -> IdentifierResolutionResult:
        return IdentifierResolutionResult(
            identifier=IdentifierView.model_validate(identifier),
            canonical_entity_id=canonical_root(self.session, identifier.entity_id).id,
            outcome=outcome,
            merge_command_id=merge_command_id,
            conflict_id=conflict_id,
        )
