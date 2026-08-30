from __future__ import annotations

from uuid import uuid4

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.contracts import (
    EntityCreate,
    ProductCodeCreate,
    ProductCodeReview,
    ProductCodeView,
    ProductConceptCreate,
    ProductConceptView,
    ProductSynonymCreate,
)
from tradefoundry.master.entities import EntityService
from tradefoundry.master.evidence import require_reliable_claim
from tradefoundry.master.models import (
    ProductCodeMappingRow,
    ProductConceptRow,
    ProductSynonymRow,
)
from tradefoundry.master.normalization import MasterDataNormalizer


class ProductOntologyService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = MasterDataNormalizer()

    def create(self, request: ProductConceptCreate) -> ProductConceptView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(ProductConceptRow).where(ProductConceptRow.concept_key == request.concept_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError(
                    f"product concept key {request.concept_key} has a different payload"
                )
            return ProductConceptView.model_validate(existing)
        require_reliable_claim(self.session, request.source_claim_id)
        if (
            request.parent_id is not None
            and self.session.get(ProductConceptRow, request.parent_id) is None
        ):
            raise LookupError(f"parent product concept {request.parent_id} not found")
        entity = EntityService(self.session).create(
            EntityCreate(
                entity_key=f"product:{request.concept_key}",
                entity_type="product",
                source_claim_id=request.source_claim_id,
                primary_name=request.preferred_label,
                language=request.language,
            )
        )
        normalized = self.normalizer.normalize_name(request.preferred_label, request.language)
        row = ProductConceptRow(
            id=str(uuid4()),
            concept_key=request.concept_key,
            request_hash=request_hash,
            entity_id=entity.id,
            preferred_label=request.preferred_label,
            normalized_label=normalized.normalized,
            parent_id=request.parent_id,
            status="active",
            source_claim_id=request.source_claim_id,
        )
        self.session.add(row)
        self.session.commit()
        return ProductConceptView.model_validate(row)

    def add_synonym(self, concept_id: str, request: ProductSynonymCreate) -> ProductSynonymRow:
        self._concept(concept_id)
        require_reliable_claim(self.session, request.source_claim_id)
        normalized = self.normalizer.normalize_name(request.label, request.language)
        existing = self.session.scalar(
            select(ProductSynonymRow).where(
                ProductSynonymRow.concept_id == concept_id,
                ProductSynonymRow.normalized_label == normalized.normalized,
                ProductSynonymRow.language == normalized.language,
                ProductSynonymRow.source_claim_id == request.source_claim_id,
            )
        )
        if existing is not None:
            return existing
        row = ProductSynonymRow(
            id=str(uuid4()),
            concept_id=concept_id,
            label=request.label,
            normalized_label=normalized.normalized,
            language=normalized.language,
            source_claim_id=request.source_claim_id,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def add_code(self, concept_id: str, request: ProductCodeCreate) -> ProductCodeView:
        self._concept(concept_id)
        require_reliable_claim(self.session, request.source_claim_id)
        code = request.code.strip().upper().replace(" ", "")
        existing = self.session.scalar(
            select(ProductCodeMappingRow).where(
                ProductCodeMappingRow.concept_id == concept_id,
                ProductCodeMappingRow.scheme == request.scheme,
                ProductCodeMappingRow.code == code,
                ProductCodeMappingRow.source_claim_id == request.source_claim_id,
            )
        )
        if existing is not None:
            if existing.confidence != request.confidence or existing.method != request.method:
                raise ValueError("product-code candidate was reused with different scoring data")
            return ProductCodeView.model_validate(existing)
        row = ProductCodeMappingRow(
            id=str(uuid4()),
            concept_id=concept_id,
            scheme=request.scheme,
            code=code,
            confidence=request.confidence,
            status="candidate",
            method=request.method,
            source_claim_id=request.source_claim_id,
        )
        self.session.add(row)
        self.session.commit()
        return ProductCodeView.model_validate(row)

    def review_code(self, mapping_id: str, request: ProductCodeReview) -> ProductCodeView:
        row = self.session.get(ProductCodeMappingRow, mapping_id)
        if row is None:
            raise LookupError(f"product code mapping {mapping_id} not found")
        if row.status in {"verified", "rejected"}:
            desired = "verified" if request.action == "verify" else "rejected"
            if row.status == desired:
                return ProductCodeView.model_validate(row)
            raise ValueError(f"mapping already has final status {row.status}")
        row.status = "verified" if request.action == "verify" else "rejected"
        row.reviewed_by = request.reviewer
        row.review_reason = request.reason
        self.session.commit()
        return ProductCodeView.model_validate(row)

    def search(self, query: str, *, limit: int = 10) -> list[tuple[ProductConceptView, float]]:
        normalized = self.normalizer.normalize_name(query).normalized
        concepts = self.session.scalars(
            select(ProductConceptRow).where(ProductConceptRow.status == "active")
        ).all()
        synonyms = self.session.scalars(select(ProductSynonymRow)).all()
        by_concept: dict[str, list[str]] = {
            concept.id: [concept.normalized_label] for concept in concepts
        }
        for synonym in synonyms:
            by_concept.setdefault(synonym.concept_id, []).append(synonym.normalized_label)
        scored = [
            (
                ProductConceptView.model_validate(concept),
                max(fuzz.WRatio(normalized, label) for label in by_concept[concept.id]) / 100,
            )
            for concept in concepts
        ]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]

    def _concept(self, concept_id: str) -> ProductConceptRow:
        row = self.session.get(ProductConceptRow, concept_id)
        if row is None:
            raise LookupError(f"product concept {concept_id} not found")
        return row
