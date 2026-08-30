from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tradefoundry.db import get_session
from tradefoundry.master.contracts import (
    CanonicalProfile,
    DistinctRequest,
    EntityCreate,
    EntitySearchHit,
    EntityView,
    IdentifierCreate,
    IdentifierResolutionResult,
    IdentityConflictReviewRequest,
    IdentityConflictView,
    MatchCandidateView,
    MatchReviewRequest,
    MergeRequest,
    MergeView,
    ProductCodeCreate,
    ProductCodeReview,
    ProductCodeView,
    ProductConceptCreate,
    ProductConceptView,
    ProductSearchHit,
    ProductSynonymCreate,
    ProductSynonymView,
    RelationCreate,
    RelationPath,
    RelationView,
    SpecificationCreate,
    SpecificationDifference,
    SpecificationView,
    SplitRequest,
    SplitView,
    UndoMergeRequest,
)
from tradefoundry.master.entities import EntityService
from tradefoundry.master.identifiers import IdentifierResolutionService
from tradefoundry.master.matching import ProbabilisticResolutionService
from tradefoundry.master.products import ProductOntologyService
from tradefoundry.master.queries import MasterQueryService
from tradefoundry.master.relations import RelationService
from tradefoundry.master.resolution import ResolutionService
from tradefoundry.master.specifications import ProductSpecificationService

router = APIRouter(prefix="/v1/master", tags=["master-data"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/entities", response_model=EntityView, status_code=201)
def create_entity(request: EntityCreate, session: Session = Depends(get_session)):
    try:
        return EntityService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/entities/{entity_id}", response_model=EntityView)
def get_entity(entity_id: str, session: Session = Depends(get_session)):
    try:
        return EntityService(session).get(entity_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/entities/{entity_id}/profile", response_model=CanonicalProfile)
def canonical_profile(entity_id: str, session: Session = Depends(get_session)):
    try:
        return EntityService(session).profile(entity_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/entities/{entity_id}/identifiers",
    response_model=IdentifierResolutionResult,
    status_code=201,
)
def add_identifier(
    entity_id: str, request: IdentifierCreate, session: Session = Depends(get_session)
):
    try:
        return IdentifierResolutionService(session).add(entity_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/identity-conflicts/{conflict_id}/review", response_model=IdentityConflictView)
def review_identity_conflict(
    conflict_id: str,
    request: IdentityConflictReviewRequest,
    session: Session = Depends(get_session),
):
    try:
        return IdentifierResolutionService(session).review_conflict(conflict_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/entities/{entity_id}/resolve", response_model=list[MatchCandidateView])
def resolve_entity(
    entity_id: str,
    auto_merge: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    try:
        return ProbabilisticResolutionService(session).resolve(entity_id, auto_merge=auto_merge)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/match-candidates/{candidate_id}/review", response_model=MatchCandidateView)
def review_match_candidate(
    candidate_id: str,
    request: MatchReviewRequest,
    session: Session = Depends(get_session),
):
    try:
        return ProbabilisticResolutionService(session).review_candidate(candidate_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/merges", response_model=MergeView, status_code=201)
def merge_entities(request: MergeRequest, session: Session = Depends(get_session)):
    try:
        return ResolutionService(session).merge(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/merges/{command_id}/undo", response_model=MergeView)
def undo_merge(
    command_id: str,
    request: UndoMergeRequest,
    session: Session = Depends(get_session),
):
    try:
        return ResolutionService(session).undo_merge(
            command_id, actor=request.actor, reason=request.reason
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/entities/{entity_id}/split", response_model=SplitView, status_code=201)
def split_entity(entity_id: str, request: SplitRequest, session: Session = Depends(get_session)):
    try:
        return ResolutionService(session).split(entity_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/distinct-pairs", status_code=201)
def mark_distinct(request: DistinctRequest, session: Session = Depends(get_session)):
    try:
        row = ResolutionService(session).mark_distinct(request)
        return {
            "id": row.id,
            "left_entity_id": row.left_entity_id,
            "right_entity_id": row.right_entity_id,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/search/names", response_model=list[EntitySearchHit])
def search_names(
    q: str = Query(min_length=1),
    language: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    return MasterQueryService(session).search_name(q, language=language, limit=limit)


@router.get("/search/identifiers", response_model=list[EntitySearchHit])
def search_identifiers(
    scheme: str,
    value: str,
    session: Session = Depends(get_session),
):
    try:
        return MasterQueryService(session).search_identifier(scheme, value)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/products", response_model=ProductConceptView, status_code=201)
def create_product(request: ProductConceptCreate, session: Session = Depends(get_session)):
    try:
        return ProductOntologyService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/products/{concept_id}/synonyms", response_model=ProductSynonymView, status_code=201)
def add_product_synonym(
    concept_id: str,
    request: ProductSynonymCreate,
    session: Session = Depends(get_session),
):
    try:
        return ProductOntologyService(session).add_synonym(concept_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/products/{concept_id}/codes", response_model=ProductCodeView, status_code=201)
def add_product_code(
    concept_id: str, request: ProductCodeCreate, session: Session = Depends(get_session)
):
    try:
        return ProductOntologyService(session).add_code(concept_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/product-codes/{mapping_id}/review", response_model=ProductCodeView)
def review_product_code(
    mapping_id: str, request: ProductCodeReview, session: Session = Depends(get_session)
):
    try:
        return ProductOntologyService(session).review_code(mapping_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/search/products", response_model=list[ProductSearchHit])
def search_products(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_session),
):
    return [
        ProductSearchHit(concept=concept, score=score)
        for concept, score in ProductOntologyService(session).search(q, limit=limit)
    ]


@router.post("/specifications", response_model=SpecificationView, status_code=201)
def create_specification(request: SpecificationCreate, session: Session = Depends(get_session)):
    try:
        return ProductSpecificationService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/specifications/{left_id}/diff/{right_id}",
    response_model=list[SpecificationDifference],
)
def specification_diff(left_id: str, right_id: str, session: Session = Depends(get_session)):
    try:
        return ProductSpecificationService(session).diff(left_id, right_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/relations", response_model=RelationView, status_code=201)
def create_relation(request: RelationCreate, session: Session = Depends(get_session)):
    try:
        return RelationService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/entities/{entity_id}/relations", response_model=list[RelationPath])
def traverse_relations(
    entity_id: str,
    max_depth: int = Query(default=3, ge=1, le=3),
    as_of: datetime | None = None,
    direction: str = Query(default="both", pattern=r"^(outgoing|incoming|both)$"),
    session: Session = Depends(get_session),
):
    try:
        return RelationService(session).traverse(
            entity_id, max_depth=max_depth, as_of=as_of, direction=direction
        )
    except Exception as exc:
        raise _error(exc) from exc
