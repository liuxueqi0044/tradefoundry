from datetime import UTC, datetime, timedelta

from deal_helpers import create_action, create_experiment, record_observation
from sqlalchemy import func, select

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.contracts import (
    ActionQueueRequest,
    ExperimentClose,
    StageTransitionRequest,
)
from tradefoundry.deals.experiments import ExperimentService
from tradefoundry.deals.models import ExperimentOutcomeRow, StageTransitionRow
from tradefoundry.deals.state_machine import RouteStageService


def test_route_state_machine_persists_rejections_and_enforces_phase_gates(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    stage = RouteStageService(session)
    rejected = stage.transition(
        route.id,
        StageTransitionRequest(
            idempotency_key="transition-without-gates",
            expected_version=1,
            to_stage="probe_ready",
            actor="operator",
            reason="Attempt before experiment setup.",
        ),
    )
    assert rejected.outcome == "rejected"
    assert "requires an Experiment" in " ".join(rejected.reasons_json)

    experiment = create_experiment(session, route.id)
    action = create_action(session, experiment.id)
    accepted = stage.transition(
        route.id,
        StageTransitionRequest(
            idempotency_key="transition-after-gates",
            expected_version=1,
            to_stage="probe_ready",
            actor="operator",
            reason="Experiment, action, budget and stop rules are ready.",
        ),
    )
    assert accepted.outcome == "accepted"
    assert (
        stage.transition(
            route.id,
            StageTransitionRequest(
                idempotency_key="transition-after-gates",
                expected_version=1,
                to_stage="probe_ready",
                actor="operator",
                reason="Experiment, action, budget and stop rules are ready.",
            ),
        ).id
        == accepted.id
    )
    illegal = stage.transition(
        route.id,
        StageTransitionRequest(
            idempotency_key="skip-to-qualified",
            expected_version=2,
            to_stage="qualified",
            actor="operator",
            reason="Try to skip intermediate gates.",
        ),
    )
    assert illegal.outcome == "rejected"
    assert session.scalar(select(func.count()).select_from(StageTransitionRow)) == 4

    ActionService(session).queue(
        action.id, ActionQueueRequest(expected_version=action.version, actor="operator")
    )
    probing = stage.transition(
        route.id,
        StageTransitionRequest(
            idempotency_key="start-probing",
            expected_version=2,
            to_stage="probing",
            actor="operator",
            reason="A bounded action is queued.",
        ),
    )
    assert probing.outcome == "accepted"


def test_experiment_has_three_outcomes_deadline_and_append_only_close(session, deal_route_factory):
    _, route = deal_route_factory(route_budget="300.00")
    service = ExperimentService(session)
    experiment = create_experiment(session, route.id, budget="200.00")
    started = service.start(experiment.id, expected_version=1)
    observation = record_observation(session, route.id, "reply", experiment_id=experiment.id)
    close = ExperimentClose(
        idempotency_key="close-demand-test",
        expected_version=started.version,
        outcome="succeeded",
        observation_ids=[observation.id],
        actor="reviewer",
        reason="A verified buyer response satisfied the success condition.",
    )
    outcome = service.close(experiment.id, close)
    assert outcome.outcome == "succeeded"
    assert service.close(experiment.id, close).id == outcome.id
    assert session.scalar(select(func.count()).select_from(ExperimentOutcomeRow)) == 1

    expired = create_experiment(
        session,
        route.id,
        key="expired-test",
        budget="50.00",
        deadline=datetime.now(UTC) - timedelta(minutes=1),
    )
    due = service.close_due(as_of=datetime.now(UTC))
    assert [item.experiment_id for item in due] == [expired.id]
    assert due[0].outcome == "inconclusive"
