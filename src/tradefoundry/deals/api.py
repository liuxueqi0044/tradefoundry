from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tradefoundry.db import get_session
from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.aggregates import DealCellService, DealRouteService
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.cockpit import DealCockpitService
from tradefoundry.deals.contracts import (
    ActionAttemptView,
    ActionCompensationRequest,
    ActionCreate,
    ActionExecutionRequest,
    ActionPolicyUpdate,
    ActionQueueItem,
    ActionQueueRequest,
    ActionView,
    BudgetAdjustmentRequest,
    BudgetAdjustmentView,
    DealCellCockpit,
    DealCellCreate,
    DealCellUpdate,
    DealCellView,
    DealRouteCreate,
    DealRouteView,
    ExpectedVersionRequest,
    ExperimentClose,
    ExperimentCreate,
    ExperimentOutcomeView,
    ExperimentView,
    ObservationCreate,
    ObservationView,
    RouteCockpit,
    RouteForkRequest,
    RouteLifecycleRequest,
    RouteMergeRequest,
    StageTransitionRequest,
    StageTransitionView,
    TimelineItem,
    WorkflowClaimRequest,
    WorkflowFailureRequest,
    WorkflowJobCreate,
    WorkflowJobView,
    WorkflowLeaseRequest,
    WorkflowSignalRequest,
    WorkflowWaitRequest,
)
from tradefoundry.deals.experiments import ExperimentService
from tradefoundry.deals.lifecycle import RouteLifecycleService
from tradefoundry.deals.observations import ObservationService
from tradefoundry.deals.queue import NextActionService
from tradefoundry.deals.state_machine import RouteStageService
from tradefoundry.deals.workflow import DatabaseWorkflowAdapter

router = APIRouter(prefix="/v1/deals", tags=["deal-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, RuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/cells", response_model=DealCellView, status_code=201)
def create_cell(request: DealCellCreate, session: Session = Depends(get_session)):
    try:
        return DealCellService(session).create(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/cells/{cell_id}", response_model=DealCellView)
def get_cell(cell_id: str, session: Session = Depends(get_session)):
    try:
        return DealCellService(session).get(cell_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.patch("/cells/{cell_id}/owner", response_model=DealCellView)
def update_cell_owner(
    cell_id: str, request: DealCellUpdate, session: Session = Depends(get_session)
):
    try:
        return DealCellService(session).update_owner(cell_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/cells/{cell_id}/routes", response_model=DealRouteView, status_code=201)
def create_route(cell_id: str, request: DealRouteCreate, session: Session = Depends(get_session)):
    try:
        return DealRouteService(session).create(cell_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/cells/{cell_id}/routes", response_model=list[DealRouteView])
def list_routes(cell_id: str, session: Session = Depends(get_session)):
    try:
        return DealRouteService(session).list(cell_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}", response_model=DealRouteView)
def get_route(route_id: str, session: Session = Depends(get_session)):
    try:
        return DealRouteService(session).get(route_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/transitions", response_model=StageTransitionView)
def transition_route(
    route_id: str, request: StageTransitionRequest, session: Session = Depends(get_session)
):
    try:
        return RouteStageService(session).transition(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/experiments", response_model=ExperimentView, status_code=201)
def create_experiment(
    route_id: str, request: ExperimentCreate, session: Session = Depends(get_session)
):
    try:
        return ExperimentService(session).create(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}/experiments", response_model=list[ExperimentView])
def list_experiments(route_id: str, session: Session = Depends(get_session)):
    return ExperimentService(session).list(route_id)


@router.post("/experiments/{experiment_id}/start", response_model=ExperimentView)
def start_experiment(
    experiment_id: str,
    request: ExpectedVersionRequest,
    session: Session = Depends(get_session),
):
    try:
        return ExperimentService(session).start(
            experiment_id, expected_version=request.expected_version
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/experiments/{experiment_id}/close", response_model=ExperimentOutcomeView)
def close_experiment(
    experiment_id: str, request: ExperimentClose, session: Session = Depends(get_session)
):
    try:
        return ExperimentService(session).close(experiment_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/experiments/close-due", response_model=list[ExperimentOutcomeView])
def close_due_experiments(session: Session = Depends(get_session)):
    try:
        return ExperimentService(session).close_due()
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/experiments/{experiment_id}/actions", response_model=ActionView, status_code=201)
def create_action(
    experiment_id: str, request: ActionCreate, session: Session = Depends(get_session)
):
    try:
        return ActionService(session).create(experiment_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}/actions", response_model=list[ActionView])
def list_actions(route_id: str, session: Session = Depends(get_session)):
    return ActionService(session).list(route_id)


@router.patch("/actions/{action_id}/policy", response_model=ActionView)
def update_action_policy(
    action_id: str, request: ActionPolicyUpdate, session: Session = Depends(get_session)
):
    try:
        return ActionService(session).update_policy(action_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/actions/{action_id}/queue", response_model=ActionView)
def queue_action(
    action_id: str, request: ActionQueueRequest, session: Session = Depends(get_session)
):
    try:
        return ActionService(session).queue(action_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/actions/{action_id}/execute", response_model=ActionAttemptView)
def execute_action(
    action_id: str, request: ActionExecutionRequest, session: Session = Depends(get_session)
):
    try:
        return ActionService(session).execute(action_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/actions/{action_id}/compensate", response_model=ActionAttemptView)
def compensate_action(
    action_id: str,
    request: ActionCompensationRequest,
    session: Session = Depends(get_session),
):
    try:
        return ActionService(session).compensate(action_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/observations", response_model=ObservationView, status_code=201)
def record_observation(
    route_id: str, request: ObservationCreate, session: Session = Depends(get_session)
):
    try:
        return ObservationService(session).record(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}/observations", response_model=list[ObservationView])
def list_observations(route_id: str, session: Session = Depends(get_session)):
    return ObservationService(session).list(route_id)


@router.post(
    "/budgets/{scope_type}/{scope_id}/adjust",
    response_model=BudgetAdjustmentView,
)
def adjust_budget(
    scope_type: str,
    scope_id: str,
    request: BudgetAdjustmentRequest,
    session: Session = Depends(get_session),
):
    try:
        return BudgetService(session).adjust(scope_type, scope_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}/next-actions", response_model=list[ActionQueueItem])
def route_next_actions(route_id: str, session: Session = Depends(get_session)):
    try:
        return NextActionService(session).evaluate_route(route_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/cells/{cell_id}/next-actions", response_model=list[ActionQueueItem])
def cell_next_actions(cell_id: str, session: Session = Depends(get_session)):
    try:
        return NextActionService(session).executable_for_cell(cell_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/pause", response_model=DealRouteView)
def pause_route(
    route_id: str, request: RouteLifecycleRequest, session: Session = Depends(get_session)
):
    try:
        return RouteLifecycleService(session).pause(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/resume", response_model=DealRouteView)
def resume_route(
    route_id: str, request: RouteLifecycleRequest, session: Session = Depends(get_session)
):
    try:
        return RouteLifecycleService(session).resume(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/terminate", response_model=DealRouteView)
def terminate_route(
    route_id: str, request: RouteLifecycleRequest, session: Session = Depends(get_session)
):
    try:
        return RouteLifecycleService(session).terminate(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{route_id}/fork", response_model=DealRouteView, status_code=201)
def fork_route(route_id: str, request: RouteForkRequest, session: Session = Depends(get_session)):
    try:
        return RouteLifecycleService(session).fork(route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/routes/{target_route_id}/merge", response_model=DealRouteView)
def merge_route(
    target_route_id: str,
    request: RouteMergeRequest,
    session: Session = Depends(get_session),
):
    try:
        return RouteLifecycleService(session).merge(target_route_id, request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/routes/{route_id}/cockpit", response_model=RouteCockpit)
def route_cockpit(route_id: str, session: Session = Depends(get_session)):
    try:
        return DealCockpitService(session).route(route_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/cells/{cell_id}/cockpit", response_model=DealCellCockpit)
def cell_cockpit(cell_id: str, session: Session = Depends(get_session)):
    try:
        return DealCockpitService(session).cell(cell_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/cells/{cell_id}/timeline", response_model=list[TimelineItem])
def cell_timeline(
    cell_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    try:
        return DealCockpitService(session).timeline(cell_id, limit=limit)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows", response_model=WorkflowJobView, status_code=201)
def enqueue_workflow(request: WorkflowJobCreate, session: Session = Depends(get_session)):
    try:
        return DatabaseWorkflowAdapter(session).enqueue(request)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/workflows/{job_id}", response_model=WorkflowJobView)
def get_workflow(job_id: str, session: Session = Depends(get_session)):
    try:
        return DatabaseWorkflowAdapter(session).get(job_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows/claim", response_model=WorkflowJobView | None)
def claim_workflow(request: WorkflowClaimRequest, session: Session = Depends(get_session)):
    try:
        return DatabaseWorkflowAdapter(session).claim_due(
            request.worker_id, lease_seconds=request.lease_seconds
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows/{job_id}/complete", response_model=WorkflowJobView)
def complete_workflow(
    job_id: str, request: WorkflowLeaseRequest, session: Session = Depends(get_session)
):
    try:
        return DatabaseWorkflowAdapter(session).complete(job_id, request.lease_token)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows/{job_id}/fail", response_model=WorkflowJobView)
def fail_workflow(
    job_id: str, request: WorkflowFailureRequest, session: Session = Depends(get_session)
):
    try:
        return DatabaseWorkflowAdapter(session).fail(
            job_id,
            request.lease_token,
            request.error,
            retry_delay_seconds=request.retry_delay_seconds,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows/{job_id}/wait", response_model=WorkflowJobView)
def wait_workflow(
    job_id: str, request: WorkflowWaitRequest, session: Session = Depends(get_session)
):
    try:
        return DatabaseWorkflowAdapter(session).wait(job_id, request.lease_token, request.reason)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/workflows/{job_id}/signals", response_model=WorkflowJobView)
def signal_workflow(
    job_id: str, request: WorkflowSignalRequest, session: Session = Depends(get_session)
):
    try:
        return DatabaseWorkflowAdapter(session).signal(job_id, request)
    except Exception as exc:
        raise _error(exc) from exc
