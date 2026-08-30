from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tradefoundry.db import get_session
from tradefoundry.tradealpha.allocation import AllocationService
from tradefoundry.tradealpha.analytics import BacktestService, CalibrationService
from tradefoundry.tradealpha.contracts import (
    ActionValuationRequest,
    ActionValuationView,
    AllocationRequest,
    AllocationResult,
    BacktestRequest,
    BacktestRunView,
    CalibrationReportView,
    CalibrationRequest,
    CashflowDistributionRequest,
    CashflowDistributionView,
    ExplorationRequest,
    ExplorationResult,
    FeatureDefinitionCreate,
    FeatureDefinitionView,
    FeatureSnapshotRequest,
    FeatureSnapshotView,
    ModelPromotionRequest,
    ModelPromotionView,
    ModelVersionCreate,
    ModelVersionView,
    PortfolioAssessmentRequest,
    PortfolioAssessmentView,
    ProbabilityEstimateRequest,
    ProbabilityEstimateView,
    RiskLimitSetCreate,
    RiskLimitSetView,
    RouteValuationRequest,
    RouteValuationView,
    ScoreExplanation,
    ScoreRequest,
    ScoreSnapshotView,
    ScoringPolicyCreate,
    ScoringPolicyView,
)
from tradefoundry.tradealpha.explanation import ExplanationService
from tradefoundry.tradealpha.exploration import ExplorationService
from tradefoundry.tradealpha.features import FeatureRegistryService, FeatureSnapshotService
from tradefoundry.tradealpha.probability import ProbabilityService
from tradefoundry.tradealpha.registry import ModelRegistryService
from tradefoundry.tradealpha.risk import RiskLimitService
from tradefoundry.tradealpha.scoring import ScoreService, ScoringPolicyService
from tradefoundry.tradealpha.valuation import (
    ActionValuationService,
    CashflowService,
    RouteValuationService,
)

router = APIRouter(prefix="/v1/tradealpha", tags=["tradealpha"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/feature-definitions", response_model=FeatureDefinitionView, status_code=201)
def create_feature_definition(
    request: FeatureDefinitionCreate, session: Session = Depends(get_session)
):
    try:
        return FeatureRegistryService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/feature-definitions/seed", response_model=list[FeatureDefinitionView])
def seed_feature_definitions(session: Session = Depends(get_session)):
    try:
        return FeatureRegistryService(session).seed_defaults()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/feature-definitions", response_model=list[FeatureDefinitionView])
def list_feature_definitions(session: Session = Depends(get_session)):
    return FeatureRegistryService(session).list_active()


@router.post(
    "/routes/{route_id}/feature-snapshots", response_model=FeatureSnapshotView, status_code=201
)
def materialize_features(
    route_id: str, request: FeatureSnapshotRequest, session: Session = Depends(get_session)
):
    try:
        return FeatureSnapshotService(session).materialize(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/scoring-policies", response_model=ScoringPolicyView, status_code=201)
def create_scoring_policy(request: ScoringPolicyCreate, session: Session = Depends(get_session)):
    try:
        return ScoringPolicyService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/scoring-policies/{policy_id}", response_model=ScoringPolicyView)
def get_scoring_policy(policy_id: str, session: Session = Depends(get_session)):
    try:
        return ScoringPolicyService(session).get(policy_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/scores", response_model=ScoreSnapshotView, status_code=201)
def score_route(route_id: str, request: ScoreRequest, session: Session = Depends(get_session)):
    try:
        return ScoreService(session).score(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/scores/{score_id}/explanation", response_model=ScoreExplanation)
def explain_score(score_id: str, session: Session = Depends(get_session)):
    try:
        return ExplanationService(session).explain(score_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/probability-estimates",
    response_model=ProbabilityEstimateView,
    status_code=201,
)
def estimate_probability(
    route_id: str, request: ProbabilityEstimateRequest, session: Session = Depends(get_session)
):
    try:
        return ProbabilityService(session).estimate(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes/{route_id}/cashflow-distributions",
    response_model=CashflowDistributionView,
    status_code=201,
)
def simulate_cashflow(
    route_id: str, request: CashflowDistributionRequest, session: Session = Depends(get_session)
):
    try:
        return CashflowService(session).simulate(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/routes/{route_id}/valuations", response_model=RouteValuationView, status_code=201)
def value_route(
    route_id: str, request: RouteValuationRequest, session: Session = Depends(get_session)
):
    try:
        return RouteValuationService(session).value(route_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/actions/{action_id}/valuations", response_model=ActionValuationView, status_code=201)
def value_action(
    action_id: str, request: ActionValuationRequest, session: Session = Depends(get_session)
):
    try:
        return ActionValuationService(session).value(action_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/risk-limit-sets", response_model=RiskLimitSetView, status_code=201)
def create_risk_limit_set(request: RiskLimitSetCreate, session: Session = Depends(get_session)):
    try:
        return RiskLimitService(session).create(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/risk-limit-sets/{limit_set_id}", response_model=RiskLimitSetView)
def get_risk_limit_set(limit_set_id: str, session: Session = Depends(get_session)):
    try:
        return RiskLimitService(session).get(limit_set_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/risk-limit-sets/{limit_set_id}/assessments",
    response_model=PortfolioAssessmentView,
    status_code=201,
)
def assess_portfolio(
    limit_set_id: str,
    request: PortfolioAssessmentRequest,
    session: Session = Depends(get_session),
):
    try:
        return RiskLimitService(session).assess(limit_set_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/risk-limit-sets/{limit_set_id}/allocations",
    response_model=AllocationResult,
    status_code=201,
)
def allocate_portfolio(
    limit_set_id: str, request: AllocationRequest, session: Session = Depends(get_session)
):
    try:
        return AllocationService(session).allocate(limit_set_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/scoring-policies/{policy_id}/backtests",
    response_model=BacktestRunView,
    status_code=201,
)
def run_backtest(policy_id: str, request: BacktestRequest, session: Session = Depends(get_session)):
    try:
        return BacktestService(session).run(policy_id, request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/calibration-reports", response_model=CalibrationReportView, status_code=201)
def create_calibration_report(request: CalibrationRequest, session: Session = Depends(get_session)):
    try:
        return CalibrationService(session).evaluate(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/model-versions", response_model=ModelVersionView, status_code=201)
def register_model(request: ModelVersionCreate, session: Session = Depends(get_session)):
    try:
        return ModelRegistryService(session).register(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/model-promotions", response_model=ModelPromotionView, status_code=201)
def promote_model(request: ModelPromotionRequest, session: Session = Depends(get_session)):
    try:
        return ModelRegistryService(session).promote(request)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/models/{model_key}/champion", response_model=ModelVersionView)
def get_champion(model_key: str, session: Session = Depends(get_session)):
    try:
        return ModelRegistryService(session).champion(model_key)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/explorations", response_model=ExplorationResult, status_code=201)
def create_exploration(request: ExplorationRequest, session: Session = Depends(get_session)):
    try:
        return ExplorationService(session).select(request)
    except Exception as exc:
        raise _http_error(exc) from exc
