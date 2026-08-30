from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.config import get_settings
from tradefoundry.db import get_session
from tradefoundry.evidence.claims import ClaimExtractionService
from tradefoundry.evidence.contracts import (
    ClaimView,
    ConversionView,
    EvidenceDocumentView,
    EvidenceFragmentView,
    EvidenceIntakeRequest,
    EvidencePackage,
    ExtractionRequest,
    ExtractionSchemaCreate,
    ExtractionSchemaView,
    ReviewRequest,
)
from tradefoundry.evidence.conversion import (
    ConversionService,
    DoclingConverterAdapter,
    StructuredTextConverter,
)
from tradefoundry.evidence.intake import FileIntakeService
from tradefoundry.evidence.models import EvidenceDocumentRow, EvidenceFragmentRow
from tradefoundry.evidence.retrieval import EvidenceRetrievalService
from tradefoundry.evidence.review import ClaimReviewService
from tradefoundry.evidence.schemas import ExtractionSchemaRegistry

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/documents", response_model=EvidenceDocumentView, status_code=201)
def ingest_document(request: EvidenceIntakeRequest, session: Session = Depends(get_session)):
    from tradefoundry.api import _artifact_store

    try:
        return FileIntakeService(
            session,
            _artifact_store(),
            production=get_settings().environment == "production",
        ).ingest(
            logical_document_id=request.logical_document_id,
            filename=request.filename,
            content=request.content(),
            declared_media_type=request.declared_media_type,
            source_url=request.source_url,
            metadata=request.metadata,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/documents/{document_id}", response_model=EvidenceDocumentView)
def get_document(document_id: str, session: Session = Depends(get_session)):
    row = session.get(EvidenceDocumentRow, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    return row


@router.post("/documents/{document_id}/convert", response_model=ConversionView)
def convert_document(
    document_id: str,
    converter: str | None = Query(default=None, pattern=r"^(structured_text|docling)$"),
    session: Session = Depends(get_session),
):
    from tradefoundry.api import _artifact_store

    selected = None
    if converter == "structured_text":
        selected = StructuredTextConverter()
    elif converter == "docling":
        selected = DoclingConverterAdapter()
    try:
        return ConversionService(session, _artifact_store()).convert(document_id, selected)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/documents/{document_id}/fragments", response_model=list[EvidenceFragmentView])
def fragments(document_id: str, session: Session = Depends(get_session)):
    return session.scalars(
        select(EvidenceFragmentRow)
        .where(EvidenceFragmentRow.document_id == document_id)
        .order_by(EvidenceFragmentRow.page_no, EvidenceFragmentRow.fragment_key)
    ).all()


@router.post("/schemas", response_model=ExtractionSchemaView, status_code=201)
def create_schema(request: ExtractionSchemaCreate, session: Session = Depends(get_session)):
    try:
        return ExtractionSchemaRegistry(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/schemas/{schema_key}", response_model=list[ExtractionSchemaView])
def list_schemas(schema_key: str, session: Session = Depends(get_session)):
    return ExtractionSchemaRegistry(session).list(schema_key)


@router.post(
    "/schemas/{schema_key}/versions/{version_no}/activate",
    response_model=ExtractionSchemaView,
)
def activate_schema(schema_key: str, version_no: int, session: Session = Depends(get_session)):
    try:
        return ExtractionSchemaRegistry(session).activate(schema_key, version_no)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/schemas/{schema_key}/versions/{version_no}/deprecate",
    response_model=ExtractionSchemaView,
)
def deprecate_schema(schema_key: str, version_no: int, session: Session = Depends(get_session)):
    try:
        return ExtractionSchemaRegistry(session).deprecate(schema_key, version_no)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/documents/{document_id}/extract", response_model=list[ClaimView])
def extract_claims(
    document_id: str, request: ExtractionRequest, session: Session = Depends(get_session)
):
    try:
        return ClaimExtractionService(session).extract(document_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/claims/{claim_id}/review", response_model=ClaimView)
def review_claim(claim_id: str, request: ReviewRequest, session: Session = Depends(get_session)):
    try:
        return ClaimReviewService(session).review(claim_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/claims/{claim_id}/package", response_model=EvidencePackage)
def evidence_package(claim_id: str, session: Session = Depends(get_session)):
    try:
        return EvidenceRetrievalService(session).package(claim_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/claims", response_model=list[ClaimView])
def claims_as_of(
    subject_key: str,
    as_of: datetime,
    session: Session = Depends(get_session),
):
    return EvidenceRetrievalService(session).claims_as_of(subject_key, as_of)
