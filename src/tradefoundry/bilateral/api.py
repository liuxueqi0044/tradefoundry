from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tradefoundry.bilateral.contracts import (
    BuyerProfileCreate,
    BuyerProfileView,
    BuyerQuoteBuildRequest,
    BuyerQuoteView,
    CandidateWhitelistRequest,
    ConstraintAssessmentRequest,
    ConstraintAssessmentView,
    ContactBundle,
    ContactCreate,
    ContactView,
    EligibilityDecisionView,
    EligibilityRequest,
    FirstContactAuthorizationRequest,
    IntentAssessmentView,
    IntentClassifyRequest,
    InteractionIntake,
    InteractionView,
    MeetingImport,
    MeetingImportResult,
    MessageDraftCreate,
    MessageDraftView,
    NegotiationTermCreate,
    NegotiationTermView,
    OutboundMessageView,
    PerformanceEventCreate,
    PerformanceEventView,
    PerformanceSnapshotRequest,
    PerformanceSnapshotView,
    QualificationCreate,
    QualificationSnapshotView,
    QuoteComparisonRequest,
    QuoteComparisonView,
    RfqAuthorizationRequest,
    RfqCreate,
    RfqFinalizeRequest,
    RfqVersionView,
    SendCommand,
    SendTokenView,
    SupplierCandidateCreate,
    SupplierCandidateView,
    SupplierProfileBundle,
    SupplierProfileCreate,
    SupplierProfileView,
    SupplierQuoteIntake,
    SupplierQuoteView,
    SuppressionCreate,
    SuppressionView,
)
from tradefoundry.bilateral.coordination import (
    BuyerQuoteService,
    ConstraintCoordinationService,
    MeetingSyncService,
    NegotiationTermService,
)
from tradefoundry.bilateral.crm import BuyerCrmService, CommunicationEligibilityService
from tradefoundry.bilateral.messaging import (
    IntentClassificationService,
    InteractionService,
    MessageDraftService,
    QualificationService,
)
from tradefoundry.bilateral.outbound import OutboundAuthorizationService, OutboundSendService
from tradefoundry.bilateral.ports import (
    CostScenarioPort,
    DenyAllPolicyPort,
    DisabledOutboundGateway,
    OutboundGateway,
    PolicyDecisionPort,
    UnavailableCostScenarioPort,
)
from tradefoundry.bilateral.quotes import QuoteComparisonService, SupplierQuoteService
from tradefoundry.bilateral.rfq import RfqService
from tradefoundry.bilateral.suppliers import (
    SupplierDiscoveryService,
    SupplierMasterService,
    SupplierPerformanceService,
)
from tradefoundry.db import get_session

router = APIRouter(prefix="/v1/bilateral", tags=["bilateral"])


def get_bilateral_policy() -> PolicyDecisionPort:
    return DenyAllPolicyPort()


def get_outbound_gateway() -> OutboundGateway:
    return DisabledOutboundGateway()


def get_cost_scenarios() -> CostScenarioPort:
    return UnavailableCostScenarioPort()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/suppliers", response_model=SupplierProfileView, status_code=201)
def create_supplier(request: SupplierProfileCreate, session: Session = Depends(get_session)):
    try:
        return SupplierMasterService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/suppliers/{supplier_id}", response_model=SupplierProfileBundle)
def get_supplier(supplier_id: str, session: Session = Depends(get_session)):
    try:
        return SupplierMasterService(session).get(supplier_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/supplier-candidates",
    response_model=SupplierCandidateView,
    status_code=201,
)
def add_supplier_candidate(
    route_id: str, request: SupplierCandidateCreate, session: Session = Depends(get_session)
):
    try:
        return SupplierDiscoveryService(session).add_candidate(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/supplier-candidates/{candidate_id}/whitelist", response_model=SupplierCandidateView)
def whitelist_supplier_candidate(
    candidate_id: str,
    request: CandidateWhitelistRequest,
    session: Session = Depends(get_session),
    policy: PolicyDecisionPort = Depends(get_bilateral_policy),
):
    try:
        return SupplierDiscoveryService(session, policy).whitelist(candidate_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/rfqs", response_model=RfqVersionView, status_code=201)
def generate_rfq(route_id: str, request: RfqCreate, session: Session = Depends(get_session)):
    try:
        return RfqService(session).generate(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/rfqs/{rfq_id}/finalize", response_model=RfqVersionView)
def finalize_rfq(rfq_id: str, request: RfqFinalizeRequest, session: Session = Depends(get_session)):
    try:
        return RfqService(session).finalize(rfq_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/rfqs/{rfq_id}/authorize", response_model=SendTokenView)
def authorize_rfq(
    rfq_id: str,
    request: RfqAuthorizationRequest,
    session: Session = Depends(get_session),
    policy: PolicyDecisionPort = Depends(get_bilateral_policy),
):
    try:
        return OutboundAuthorizationService(session, policy).authorize_rfq(
            rfq_id, request.supplier_profile_id, requested_by=request.requested_by
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/outbound/send", response_model=OutboundMessageView)
def send_outbound(
    request: SendCommand,
    session: Session = Depends(get_session),
    gateway: OutboundGateway = Depends(get_outbound_gateway),
):
    try:
        return OutboundSendService(session, gateway).send(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/supplier-quotes", response_model=SupplierQuoteView, status_code=201
)
def intake_supplier_quote(
    route_id: str, request: SupplierQuoteIntake, session: Session = Depends(get_session)
):
    try:
        return SupplierQuoteService(session).intake(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/quote-comparisons", response_model=QuoteComparisonView, status_code=201
)
def compare_supplier_quotes(
    route_id: str, request: QuoteComparisonRequest, session: Session = Depends(get_session)
):
    try:
        return QuoteComparisonService(session).compare(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/suppliers/{supplier_id}/performance-events",
    response_model=PerformanceEventView,
    status_code=201,
)
def record_supplier_performance(
    supplier_id: str, request: PerformanceEventCreate, session: Session = Depends(get_session)
):
    try:
        return SupplierPerformanceService(session).record_event(supplier_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/suppliers/{supplier_id}/performance-snapshots",
    response_model=PerformanceSnapshotView,
    status_code=201,
)
def snapshot_supplier_performance(
    supplier_id: str,
    request: PerformanceSnapshotRequest,
    session: Session = Depends(get_session),
):
    try:
        return SupplierPerformanceService(session).snapshot(supplier_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/buyers", response_model=BuyerProfileView, status_code=201)
def create_buyer(request: BuyerProfileCreate, session: Session = Depends(get_session)):
    try:
        return BuyerCrmService(session).create_buyer(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/contacts", response_model=ContactView, status_code=201)
def create_contact(request: ContactCreate, session: Session = Depends(get_session)):
    try:
        return BuyerCrmService(session).create_contact(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/contacts/{contact_id}", response_model=ContactBundle)
def get_contact(contact_id: str, session: Session = Depends(get_session)):
    try:
        return BuyerCrmService(session).get_contact(contact_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/contacts/{contact_id}/suppressions", response_model=SuppressionView, status_code=201)
def suppress_contact(
    contact_id: str, request: SuppressionCreate, session: Session = Depends(get_session)
):
    try:
        return CommunicationEligibilityService(session, DenyAllPolicyPort()).suppress(
            contact_id, request
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/contacts/{contact_id}/eligibility",
    response_model=EligibilityDecisionView,
    status_code=201,
)
def evaluate_contact_eligibility(
    contact_id: str,
    request: EligibilityRequest,
    session: Session = Depends(get_session),
    policy: PolicyDecisionPort = Depends(get_bilateral_policy),
):
    try:
        return CommunicationEligibilityService(session, policy).evaluate(contact_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/message-drafts", response_model=MessageDraftView, status_code=201)
def create_message_draft(
    route_id: str, request: MessageDraftCreate, session: Session = Depends(get_session)
):
    try:
        return MessageDraftService(session).create(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/message-drafts/{draft_id}/authorize", response_model=SendTokenView)
def authorize_first_contact(
    draft_id: str,
    request: FirstContactAuthorizationRequest,
    session: Session = Depends(get_session),
    policy: PolicyDecisionPort = Depends(get_bilateral_policy),
):
    try:
        return OutboundAuthorizationService(session, policy).authorize_first_contact(
            draft_id, requested_by=request.requested_by
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/interactions", response_model=InteractionView, status_code=201)
def intake_interaction(request: InteractionIntake, session: Session = Depends(get_session)):
    try:
        return InteractionService(session).intake(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/interactions/{interaction_id}/intent", response_model=IntentAssessmentView, status_code=201
)
def classify_intent(
    interaction_id: str,
    request: IntentClassifyRequest,
    session: Session = Depends(get_session),
):
    try:
        return IntentClassificationService(session).classify(interaction_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/qualifications",
    response_model=QualificationSnapshotView,
    status_code=201,
)
def create_qualification(
    route_id: str, request: QualificationCreate, session: Session = Depends(get_session)
):
    try:
        return QualificationService(session).snapshot(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/constraint-assessments",
    response_model=ConstraintAssessmentView,
    status_code=201,
)
def assess_constraints(
    route_id: str,
    request: ConstraintAssessmentRequest,
    session: Session = Depends(get_session),
):
    try:
        return ConstraintCoordinationService(session).assess(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/buyer-quotes", response_model=BuyerQuoteView, status_code=201)
def build_buyer_quote(
    route_id: str,
    request: BuyerQuoteBuildRequest,
    session: Session = Depends(get_session),
    costs: CostScenarioPort = Depends(get_cost_scenarios),
):
    try:
        return BuyerQuoteService(session, costs).build(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/negotiation-terms",
    response_model=NegotiationTermView,
    status_code=201,
)
def append_negotiation_terms(
    route_id: str, request: NegotiationTermCreate, session: Session = Depends(get_session)
):
    try:
        return NegotiationTermService(session).append(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/meetings", response_model=MeetingImportResult, status_code=201)
def import_meeting(route_id: str, request: MeetingImport, session: Session = Depends(get_session)):
    try:
        return MeetingSyncService(session).import_meeting(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc
