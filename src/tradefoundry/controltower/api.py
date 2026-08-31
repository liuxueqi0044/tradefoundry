from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tradefoundry.controltower.audit import AuditExportService
from tradefoundry.controltower.contracts import (
    ApprovalDecisionCreate,
    ApprovalRequestCreate,
    ApprovalRequestView,
    ApprovalStepView,
    AuditExportCreate,
    AuditExportView,
    CashflowEventView,
    CashflowPlanCreate,
    CashflowPlanView,
    CommunicationDecisionView,
    CommunicationEvaluate,
    ComplianceDatasetView,
    ComplianceSyncAttemptView,
    CostDefinitionCreate,
    CostDefinitionView,
    CreditAssessmentCreate,
    CreditAssessmentView,
    CreditOverrideCreate,
    CreditOverrideView,
    DatasetSyncCreate,
    DatasetSyncFailure,
    ExecutionTokenIssue,
    ExecutionTokenView,
    ExportControlCreate,
    ExportControlView,
    FreezeRelease,
    FreezeReleaseView,
    FreezeView,
    FxQuoteCreate,
    FxQuoteView,
    LandedCostCreate,
    LandedCostLineView,
    LandedCostView,
    MoneyConversionCreate,
    MoneyConversionView,
    PolicyBundleCreate,
    PolicyBundleView,
    PolicyDecisionCreate,
    PolicyDecisionView,
    RiskCaseOpen,
    RiskCaseView,
    ScreeningCreate,
    ScreeningMatchView,
    ScreeningView,
    SensitivityCreate,
    SensitivityView,
    TradeRequirementCreate,
    TradeRequirementView,
)
from tradefoundry.controltower.datasets import ComplianceDatasetService
from tradefoundry.controltower.finance import (
    CashflowService,
    CostService,
    CreditService,
    MoneyService,
    SensitivityService,
)
from tradefoundry.controltower.governance import (
    ApprovalService,
    ExecutionTokenService,
    FreezeService,
)
from tradefoundry.controltower.policy import PolicyBundleService, PolicyEngine
from tradefoundry.controltower.privacy import CommunicationPolicyService
from tradefoundry.controltower.screening import ScreeningService
from tradefoundry.controltower.trade_rules import (
    ExportControlService,
    TradeRequirementService,
)
from tradefoundry.db import get_session

router = APIRouter(prefix="/v1/control", tags=["control-tower"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/fx-quotes", response_model=FxQuoteView, status_code=201)
def create_fx_quote(request: FxQuoteCreate, session: Session = Depends(get_session)):
    try:
        return MoneyService(session).create_quote(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/money-conversions", response_model=MoneyConversionView, status_code=201)
def convert_money(request: MoneyConversionCreate, session: Session = Depends(get_session)):
    try:
        return MoneyService(session).convert(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/cost-definitions", response_model=CostDefinitionView, status_code=201)
def create_cost_definition(request: CostDefinitionCreate, session: Session = Depends(get_session)):
    try:
        return CostService(session).create_definition(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/landed-cost-scenarios", response_model=LandedCostView, status_code=201)
def calculate_landed_cost(request: LandedCostCreate, session: Session = Depends(get_session)):
    try:
        return CostService(session).calculate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/landed-cost-scenarios/{scenario_id}/lines",
    response_model=list[LandedCostLineView],
)
def landed_cost_lines(scenario_id: str, session: Session = Depends(get_session)):
    try:
        return CostService(session).lines(scenario_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/cashflow-plans", response_model=CashflowPlanView, status_code=201)
def calculate_cashflow(request: CashflowPlanCreate, session: Session = Depends(get_session)):
    try:
        return CashflowService(session).calculate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cashflow-plans/{plan_id}/events", response_model=list[CashflowEventView])
def cashflow_events(plan_id: str, session: Session = Depends(get_session)):
    try:
        return CashflowService(session).events(plan_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/sensitivity-runs", response_model=SensitivityView, status_code=201)
def calculate_sensitivity(request: SensitivityCreate, session: Session = Depends(get_session)):
    try:
        return SensitivityService(session).calculate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/credit-assessments", response_model=CreditAssessmentView, status_code=201)
def assess_credit(request: CreditAssessmentCreate, session: Session = Depends(get_session)):
    try:
        return CreditService(session).assess(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/credit-assessments/{assessment_id}/overrides",
    response_model=CreditOverrideView,
    status_code=201,
)
def override_credit(
    assessment_id: str,
    request: CreditOverrideCreate,
    session: Session = Depends(get_session),
):
    try:
        return CreditService(session).override(assessment_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/datasets/sync", response_model=ComplianceDatasetView, status_code=201)
def sync_dataset(request: DatasetSyncCreate, session: Session = Depends(get_session)):
    try:
        return ComplianceDatasetService(session).sync(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/datasets/sync-failures", response_model=ComplianceSyncAttemptView, status_code=201)
def record_dataset_failure(request: DatasetSyncFailure, session: Session = Depends(get_session)):
    try:
        return ComplianceDatasetService(session).record_failure(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/screenings", response_model=ScreeningView, status_code=201)
def screen_entity(request: ScreeningCreate, session: Session = Depends(get_session)):
    try:
        return ScreeningService(session).screen(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/screenings/{screening_id}/matches", response_model=list[ScreeningMatchView])
def screening_matches(screening_id: str, session: Session = Depends(get_session)):
    try:
        return ScreeningService(session).matches(screening_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/export-control-assessments", response_model=ExportControlView, status_code=201)
def assess_export_control(request: ExportControlCreate, session: Session = Depends(get_session)):
    try:
        return ExportControlService(session).assess(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/trade-requirement-assessments",
    response_model=TradeRequirementView,
    status_code=201,
)
def assess_trade_requirements(
    request: TradeRequirementCreate, session: Session = Depends(get_session)
):
    try:
        return TradeRequirementService(session).assess(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/policy-bundles", response_model=PolicyBundleView, status_code=201)
def create_policy_bundle(request: PolicyBundleCreate, session: Session = Depends(get_session)):
    try:
        return PolicyBundleService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/policy-bundles/{bundle_id}/activate", response_model=PolicyBundleView)
def activate_policy_bundle(bundle_id: str, session: Session = Depends(get_session)):
    try:
        return PolicyBundleService(session).activate(bundle_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/policy-decisions", response_model=PolicyDecisionView, status_code=201)
def evaluate_policy(request: PolicyDecisionCreate, session: Session = Depends(get_session)):
    try:
        return PolicyEngine(session).decide(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/communication-decisions", response_model=CommunicationDecisionView, status_code=201)
def evaluate_communication(request: CommunicationEvaluate, session: Session = Depends(get_session)):
    try:
        return CommunicationPolicyService(session).evaluate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/approval-requests", response_model=ApprovalRequestView, status_code=201)
def create_approval(request: ApprovalRequestCreate, session: Session = Depends(get_session)):
    try:
        return ApprovalService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/approval-requests/{approval_id}", response_model=ApprovalRequestView)
def get_approval(approval_id: str, session: Session = Depends(get_session)):
    try:
        return ApprovalService(session).get(approval_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/approval-requests/{approval_id}/steps", response_model=list[ApprovalStepView])
def approval_steps(approval_id: str, session: Session = Depends(get_session)):
    try:
        return ApprovalService(session).steps(approval_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/approval-requests/{approval_id}/decisions", response_model=ApprovalRequestView)
def decide_approval(
    approval_id: str,
    request: ApprovalDecisionCreate,
    session: Session = Depends(get_session),
):
    try:
        return ApprovalService(session).decide(approval_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/execution-tokens", response_model=ExecutionTokenView, status_code=201)
def issue_execution_token(request: ExecutionTokenIssue, session: Session = Depends(get_session)):
    try:
        return ExecutionTokenService(session).issue(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/risk-cases", response_model=RiskCaseView, status_code=201)
def open_risk_case(request: RiskCaseOpen, session: Session = Depends(get_session)):
    try:
        return FreezeService(session).open_case(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/freezes", response_model=list[FreezeView])
def active_freezes(
    subject_ref: list[str] = Query(min_length=1),
    action: str = Query(min_length=1),
    session: Session = Depends(get_session),
):
    return FreezeService(session).active_freezes(subject_ref, action)


@router.post("/freezes/{freeze_id}/release", response_model=FreezeReleaseView, status_code=201)
def release_freeze(freeze_id: str, request: FreezeRelease, session: Session = Depends(get_session)):
    try:
        return FreezeService(session).release(freeze_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/audit-exports", response_model=AuditExportView, status_code=201)
def export_audit_package(request: AuditExportCreate, session: Session = Depends(get_session)):
    try:
        return AuditExportService(session).export(request)
    except Exception as exc:
        raise _http_error(exc) from exc
