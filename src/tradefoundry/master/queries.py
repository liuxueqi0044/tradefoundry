from __future__ import annotations

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.master.contracts import EntitySearchHit
from tradefoundry.master.identifiers import IdentifierResolutionService
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import EntityAliasRow, EntityIdentifierRow, EntityRow
from tradefoundry.master.normalization import MasterDataNormalizer


class MasterQueryService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = MasterDataNormalizer()

    def search_name(
        self, query: str, *, language: str | None = None, limit: int = 20
    ) -> list[EntitySearchHit]:
        normalized = self.normalizer.normalize_name(query, language).normalized
        rows = self.session.scalars(select(EntityAliasRow)).all()
        best: dict[str, EntitySearchHit] = {}
        for row in rows:
            if language and row.language != language:
                continue
            root = canonical_root(self.session, row.entity_id)
            score = fuzz.WRatio(normalized, row.normalized_value) / 100.0
            hit = EntitySearchHit(
                canonical_entity_id=root.id,
                entity_type=root.entity_type,
                matched_alias=row.raw_value,
                normalized_alias=row.normalized_value,
                score=score,
                source_claim_id=row.source_claim_id,
            )
            if root.id not in best or best[root.id].score < score:
                best[root.id] = hit
        return sorted(best.values(), key=lambda item: item.score, reverse=True)[:limit]

    def search_identifier(self, scheme: str, value: str) -> list[EntitySearchHit]:
        scheme = scheme.lower()
        normalized = IdentifierResolutionService(self.session).normalize(scheme, value)
        rows = self.session.scalars(
            select(EntityIdentifierRow).where(
                EntityIdentifierRow.scheme == scheme,
                EntityIdentifierRow.normalized_value == normalized,
            )
        ).all()
        hits: dict[str, EntitySearchHit] = {}
        for row in rows:
            root = canonical_root(self.session, row.entity_id)
            entity = self.session.get(EntityRow, root.id)
            hits[root.id] = EntitySearchHit(
                canonical_entity_id=root.id,
                entity_type=entity.entity_type,
                matched_alias=row.raw_value,
                normalized_alias=row.normalized_value,
                score=1.0,
                source_claim_id=row.source_claim_id,
            )
        return list(hits.values())
