from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    AliasInput,
    AliasView,
    CanonicalProfile,
    EntityCreate,
    EntityView,
    GoldenField,
    IdentifierView,
)
from tradefoundry.master.evidence import require_reliable_claim
from tradefoundry.master.identity import canonical_member_ids, canonical_root
from tradefoundry.master.models import (
    EntityAliasRow,
    EntityAttributeRow,
    EntityIdentifierRow,
    EntityRow,
)
from tradefoundry.master.normalization import MasterDataNormalizer


class EntityService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = MasterDataNormalizer()

    def create(self, request: EntityCreate) -> EntityView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(EntityRow).where(EntityRow.entity_key == request.entity_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError(
                    f"entity key {request.entity_key} was reused with a different payload"
                )
            return EntityView.model_validate(existing)
        require_reliable_claim(self.session, request.source_claim_id)
        row = EntityRow(
            id=str(uuid4()),
            entity_key=request.entity_key,
            request_hash=request_hash,
            entity_type=request.entity_type.value,
            source_claim_id=request.source_claim_id,
            risk_tier=request.risk_tier,
            status="active",
        )
        self.session.add(row)
        self.session.flush()
        self._add_alias(
            row.id,
            AliasInput(
                value=request.primary_name,
                language=request.language,
                alias_type="primary",
                confidence=1.0,
            ),
            request.source_claim_id,
        )
        for alias in request.aliases:
            self._add_alias(row.id, alias, request.source_claim_id)
        for attribute in request.attributes:
            normalized = self._normalize_attribute(attribute.field_name, attribute.value)
            self.session.add(
                EntityAttributeRow(
                    id=str(uuid4()),
                    entity_id=row.id,
                    field_name=attribute.field_name,
                    raw_value_json=attribute.value,
                    normalized_value_json=normalized,
                    raw_hash=payload_hash(attribute.value),
                    source_claim_id=request.source_claim_id,
                    confidence=attribute.confidence,
                    source_priority=attribute.source_priority,
                    valid_from=attribute.valid_from,
                    valid_to=attribute.valid_to,
                )
            )
        self.session.commit()
        return EntityView.model_validate(row)

    def get(self, entity_id: str) -> EntityView:
        row = self.session.get(EntityRow, entity_id)
        if row is None:
            raise LookupError(f"entity {entity_id} not found")
        return EntityView.model_validate(row)

    def profile(self, entity_id: str) -> CanonicalProfile:
        root = canonical_root(self.session, entity_id)
        member_ids = canonical_member_ids(self.session, root.id)
        aliases = self.session.scalars(
            select(EntityAliasRow)
            .where(EntityAliasRow.entity_id.in_(member_ids))
            .order_by(EntityAliasRow.confidence.desc(), EntityAliasRow.created_at)
        ).all()
        identifiers = self.session.scalars(
            select(EntityIdentifierRow)
            .where(EntityIdentifierRow.entity_id.in_(member_ids))
            .order_by(EntityIdentifierRow.scheme, EntityIdentifierRow.normalized_value)
        ).all()
        attributes = self.session.scalars(
            select(EntityAttributeRow).where(EntityAttributeRow.entity_id.in_(member_ids))
        ).all()
        source_claim_ids = {attribute.source_claim_id for attribute in attributes} | {
            alias.source_claim_id for alias in aliases
        }
        claims = {
            claim.id: claim
            for claim in self.session.scalars(
                select(ClaimRow).where(ClaimRow.id.in_(source_claim_ids))
            ).all()
        }
        golden: dict[str, GoldenField] = {}
        if aliases:
            selected_alias = max(
                aliases,
                key=lambda item: (
                    2 if claims[item.source_claim_id].status == "verified" else 1,
                    1 if item.alias_type == "primary" else 0,
                    item.confidence,
                    item.created_at.timestamp(),
                ),
            )
            golden["name"] = GoldenField(
                value=selected_alias.normalized_value,
                raw_value=selected_alias.raw_value,
                source_entity_id=selected_alias.entity_id,
                source_claim_id=selected_alias.source_claim_id,
                confidence=selected_alias.confidence,
                source_priority=0,
                selection_reason=(
                    "highest name provenance rank: "
                    f"claim={claims[selected_alias.source_claim_id].status}, "
                    f"alias_type={selected_alias.alias_type}, "
                    f"confidence={selected_alias.confidence}"
                ),
            )
        grouped: dict[str, list[EntityAttributeRow]] = defaultdict(list)
        for attribute in attributes:
            grouped[attribute.field_name].append(attribute)
        for field_name, candidates in grouped.items():
            selected = max(candidates, key=lambda item: self._golden_rank(item, claims))
            claim_status = claims.get(selected.source_claim_id).status
            golden[field_name] = GoldenField(
                value=selected.normalized_value_json,
                raw_value=selected.raw_value_json,
                source_entity_id=selected.entity_id,
                source_claim_id=selected.source_claim_id,
                confidence=selected.confidence,
                source_priority=selected.source_priority,
                selection_reason=(
                    f"highest provenance rank: claim={claim_status}, "
                    f"priority={selected.source_priority}, confidence={selected.confidence}"
                ),
            )
        return CanonicalProfile(
            canonical_entity=EntityView.model_validate(root),
            member_ids=member_ids,
            aliases=[AliasView.model_validate(alias) for alias in aliases],
            identifiers=[IdentifierView.model_validate(identifier) for identifier in identifiers],
            golden_fields=golden,
        )

    def _add_alias(self, entity_id: str, alias: AliasInput, claim_id: str) -> None:
        normalized = self.normalizer.normalize_name(alias.value, alias.language)
        if not normalized.normalized:
            raise ValueError("entity alias becomes empty after normalization")
        self.session.add(
            EntityAliasRow(
                id=str(uuid4()),
                entity_id=entity_id,
                raw_value=normalized.raw,
                normalized_value=normalized.normalized,
                tokens_json=normalized.tokens,
                language=normalized.language,
                alias_type=alias.alias_type,
                source_claim_id=claim_id,
                confidence=alias.confidence,
            )
        )

    def _normalize_attribute(self, field_name: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if field_name == "address":
            return self.normalizer.normalize_address(value).normalized
        if field_name == "domain":
            return self.normalizer.normalize_domain(value)
        if field_name == "email":
            return self.normalizer.normalize_email(value)
        if field_name == "phone":
            return self.normalizer.normalize_phone(value)
        if field_name in {"country", "country_code"}:
            return value.strip().upper()
        return unicodedata.normalize("NFKC", value).strip()

    @staticmethod
    def _golden_rank(
        attribute: EntityAttributeRow, claims: dict[str, ClaimRow]
    ) -> tuple[int, int, float, float]:
        claim = claims.get(attribute.source_claim_id)
        review_rank = 2 if claim and claim.status == "verified" else 1
        return (
            review_rank,
            attribute.source_priority,
            attribute.confidence,
            attribute.created_at.timestamp(),
        )
