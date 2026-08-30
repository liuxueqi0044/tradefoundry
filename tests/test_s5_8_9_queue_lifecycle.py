from datetime import UTC, datetime, timedelta
from decimal import Decimal

from deal_helpers import create_action, create_experiment, record_observation
from sqlalchemy import func, select

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.contracts import (
    ActionExecutionRequest,
    ActionQueueRequest,
    RouteForkRequest,
    RouteLifecycleRequest,
    RouteMergeRequest,
)
from tradefoundry.deals.lifecycle import RouteLifecycleService
from tradefoundry.deals.models import (
    DealRouteRow,
    RouteEvidenceLinkRow,
    RouteLifecycleEventRow,
    StageTransitionRow,
)
from tradefoundry.deals.queue import NextActionService


def test_next_action_queue_explains_dependencies_policy_budget_deadline_and_sla(
    session, deal_route_factory
):
    cell, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    first = create_action(
        session,
        experiment.id,
        key="collect-contact",
        due_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    dependent = create_action(
        session,
        experiment.id,
        key="prepare-probe",
        dependencies=[first.id],
    )
    external = create_action(
        session,
        experiment.id,
        key="send-probe",
        external=True,
        policy_status="approved",
        policy_ref="unverified-policy-ref",
    )

    items = NextActionService(session).evaluate_route(route.id)
    by_id = {item.action.id: item for item in items}
    assert by_id[first.id].executable is True
    assert by_id[first.id].overdue is True
    assert "dependencies incomplete" in " ".join(by_id[dependent.id].blockers)
    assert "could not be verified" in " ".join(by_id[external.id].blockers)
    assert by_id[first.id].action.sla_seconds == 3600

    service = ActionService(session)
    queued = service.queue(
        first.id, ActionQueueRequest(expected_version=first.version, actor="operator")
    )
    service.execute(
        first.id,
        ActionExecutionRequest(expected_version=queued.version, actor="operator"),
    )
    refreshed = {
        item.action.id: item for item in NextActionService(session).evaluate_route(route.id)
    }
    assert refreshed[dependent.id].executable is True
    executable = NextActionService(session).executable_for_cell(cell.id)
    assert dependent.id in {item.action.id for item in executable}


def test_route_fork_pause_resume_merge_keep_independent_budgets_and_history(
    session, deal_route_factory
):
    _, parent = deal_route_factory()
    original_observation = record_observation(session, parent.id, "reply")
    service = RouteLifecycleService(session)
    pause_request = RouteLifecycleRequest(
        idempotency_key="pause-parent-route",
        expected_version=1,
        actor="route-owner",
        reason="Pause while validating a channel constraint.",
    )
    paused = service.pause(parent.id, pause_request)
    assert paused.lifecycle_status == "paused"
    assert service.pause(parent.id, pause_request).version == paused.version
    resumed = service.resume(
        parent.id,
        RouteLifecycleRequest(
            idempotency_key="resume-parent-route",
            expected_version=paused.version,
            actor="route-owner",
            reason="Channel constraint has been resolved.",
        ),
    )
    child = service.fork(
        parent.id,
        RouteForkRequest(
            idempotency_key="fork-parent-route",
            expected_version=resumed.version,
            actor="route-owner",
            reason="Test a partner-assisted variant independently.",
            route_key="partner-assisted-fork",
            amount=Decimal("200.00"),
            currency="USD",
        ),
    )
    repeated = service.fork(
        parent.id,
        RouteForkRequest(
            idempotency_key="fork-parent-route",
            expected_version=resumed.version,
            actor="route-owner",
            reason="Test a partner-assisted variant independently.",
            route_key="partner-assisted-fork",
            amount=Decimal("200.00"),
            currency="USD",
        ),
    )
    assert repeated.id == child.id
    assert child.parent_route_id == parent.id
    assert child.budget_limit == Decimal("200.00")
    link = session.scalar(
        select(RouteEvidenceLinkRow).where(
            RouteEvidenceLinkRow.route_id == child.id,
            RouteEvidenceLinkRow.observation_id == original_observation.id,
        )
    )
    assert link.inherited_from_route_id == parent.id

    child_observation = record_observation(session, child.id, "meeting")
    parent_now = session.get(DealRouteRow, parent.id)
    merged_target = service.merge(
        parent.id,
        RouteMergeRequest(
            idempotency_key="merge-child-route",
            source_route_id=child.id,
            target_expected_version=parent_now.version,
            source_expected_version=child.version,
            actor="route-owner",
            reason="Partner-assisted evidence is now part of the primary route.",
        ),
    )
    merged_child = session.get(DealRouteRow, child.id)
    assert merged_target.id == parent.id
    assert merged_child.lifecycle_status == "merged"
    assert merged_child.merged_into_route_id == parent.id
    assert (
        session.scalar(
            select(func.count())
            .select_from(RouteEvidenceLinkRow)
            .where(
                RouteEvidenceLinkRow.route_id == parent.id,
                RouteEvidenceLinkRow.observation_id == child_observation.id,
            )
        )
        == 1
    )
    assert session.scalar(select(func.count()).select_from(StageTransitionRow)) == 2
    assert session.scalar(select(func.count()).select_from(RouteLifecycleEventRow)) == 4


def test_route_termination_is_explicit_and_versioned(session, deal_route_factory):
    _, route = deal_route_factory()
    terminated = RouteLifecycleService(session).terminate(
        route.id,
        RouteLifecycleRequest(
            idempotency_key="terminate-unviable-route",
            expected_version=route.version,
            actor="route-owner",
            reason="A hard stop condition has been verified.",
        ),
    )
    assert terminated.lifecycle_status == "terminated"
