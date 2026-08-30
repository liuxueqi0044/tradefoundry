from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tradefoundry.db import get_session
from tradefoundry.opportunity.auditor import HypothesisAuditor
from tradefoundry.opportunity.compiler import OpportunityCompiler
from tradefoundry.opportunity.contracts import (
    AuditRequest,
    AuditView,
    CompileRequest,
    HypothesisView,
    IssuanceRequest,
    IssuanceView,
    LLMProductNeedProposal,
    ParticipantView,
    ProductNeedView,
    RouteView,
    SignalView,
    TemplateCreate,
    TemplateStateRequest,
    TemplateView,
    WorldEventCreate,
    WorldEventView,
)
from tradefoundry.opportunity.events import WorldEventService
from tradefoundry.opportunity.issuance import DealCellIssuanceService
from tradefoundry.opportunity.needs import ProductNeedService
from tradefoundry.opportunity.participants import ParticipantDiscoveryService
from tradefoundry.opportunity.routes import RouteCandidateService
from tradefoundry.opportunity.signals import SignalClassifier
from tradefoundry.opportunity.templates import OpportunityTemplateService

router = APIRouter(prefix="/v1/opportunities", tags=["opportunity-compiler"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/events", response_model=WorldEventView, status_code=201)
def build_event(request: WorldEventCreate, session: Session = Depends(get_session)):
    try:
        return WorldEventService(session).build(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/events/{event_id}", response_model=WorldEventView)
def get_event(event_id: str, session: Session = Depends(get_session)):
    try:
        return WorldEventService(session).get(event_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/events/{event_id}/classify", response_model=list[SignalView])
def classify_event(event_id: str, session: Session = Depends(get_session)):
    try:
        return SignalClassifier(session).classify(event_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/templates", response_model=TemplateView, status_code=201)
def create_template(request: TemplateCreate, session: Session = Depends(get_session)):
    try:
        return OpportunityTemplateService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/templates/{template_id}", response_model=TemplateView)
def get_template(template_id: str, session: Session = Depends(get_session)):
    try:
        return OpportunityTemplateService(session).get(template_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/templates/{template_id}/activate", response_model=TemplateView)
def activate_template(
    template_id: str,
    request: TemplateStateRequest,
    session: Session = Depends(get_session),
):
    try:
        return OpportunityTemplateService(session).activate(template_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/templates/{template_id}/deprecate", response_model=TemplateView)
def deprecate_template(
    template_id: str,
    request: TemplateStateRequest,
    session: Session = Depends(get_session),
):
    try:
        return OpportunityTemplateService(session).deprecate(template_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/events/{event_id}/templates", response_model=list[TemplateView])
def applicable_templates(event_id: str, session: Session = Depends(get_session)):
    try:
        return OpportunityTemplateService(session).applicable(event_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/events/{event_id}/templates/{template_id}/needs",
    response_model=list[ProductNeedView],
)
def derive_needs(
    event_id: str,
    template_id: str,
    session: Session = Depends(get_session),
):
    try:
        return ProductNeedService(session).derive(event_id, template_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/events/{event_id}/templates/{template_id}/need-proposals",
    response_model=ProductNeedView,
    status_code=201,
)
def propose_need(
    event_id: str,
    template_id: str,
    request: LLMProductNeedProposal,
    session: Session = Depends(get_session),
):
    try:
        return ProductNeedService(session).propose(event_id, template_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/events/{event_id}/participants", response_model=list[ParticipantView])
def discover_participants(event_id: str, session: Session = Depends(get_session)):
    try:
        return ParticipantDiscoveryService(session).discover(event_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/events/{event_id}/routes", response_model=list[RouteView])
def generate_routes(event_id: str, session: Session = Depends(get_session)):
    try:
        return RouteCandidateService(session).generate(event_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/hypotheses/compile", response_model=list[HypothesisView], status_code=201)
def compile_hypotheses(request: CompileRequest, session: Session = Depends(get_session)):
    try:
        return OpportunityCompiler(session).compile(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/hypotheses/{hypothesis_id}", response_model=HypothesisView)
def get_hypothesis(hypothesis_id: str, session: Session = Depends(get_session)):
    try:
        return OpportunityCompiler(session).get(hypothesis_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/audit", response_model=AuditView)
def audit_hypothesis(
    hypothesis_id: str,
    request: AuditRequest,
    session: Session = Depends(get_session),
):
    try:
        return HypothesisAuditor(session).audit(hypothesis_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/issue", response_model=IssuanceView)
def issue_hypothesis(
    hypothesis_id: str,
    request: IssuanceRequest,
    session: Session = Depends(get_session),
):
    try:
        return DealCellIssuanceService(session).issue(hypothesis_id, request)
    except Exception as exc:
        raise _error(exc) from exc
