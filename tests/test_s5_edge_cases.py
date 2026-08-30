from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from deal_helpers import create_action, create_experiment, record_observation

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.aggregates import DealRouteService, OptimisticLockError
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.contracts import (
    ActionCompensationRequest,
    ActionCreate,
    ActionExecutionRequest,
    ActionPolicyUpdate,
    ActionQueueRequest,
    BudgetAdjustmentRequest,
    ExperimentClose,
    ExperimentCreate,
    ObservationCreate,
    RouteForkRequest,
    RouteLifecycleRequest,
    StageTransitionRequest,
    WorkflowJobCreate,
)
from tradefoundry.deals.experiments import ExperimentService
from tradefoundry.deals.lifecycle import RouteLifecycleService
from tradefoundry.deals.observations import ObservationService
from tradefoundry.deals.ports import InternalNoopExecutor
from tradefoundry.deals.state_machine import RouteStageService


def _transition(session, route, target, key):
    current = DealRouteService(session).get(route.id)
    return RouteStageService(session).transition(
        route.id,
        StageTransitionRequest(
            idempotency_key=key,
            expected_version=current.version,
            to_stage=target,
            actor="acceptance-operator",
            reason=f"Advance through the verified {target} gate.",
        ),
    )


def test_every_route_phase_gate_requires_then_snapshots_configured_evidence(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    action = create_action(session, experiment.id)
    queued = ActionService(session).queue(
        action.id, ActionQueueRequest(expected_version=1, actor="operator")
    )
    ActionService(session).execute(
        action.id,
        ActionExecutionRequest(expected_version=queued.version, actor="operator"),
    )
    assert _transition(session, route, "probe_ready", "phase-probe-ready").outcome == "accepted"
    assert _transition(session, route, "probing", "phase-probing").outcome == "accepted"
    assert _transition(session, route, "engaged", "phase-engaged-denied").outcome == "rejected"
    record_observation(session, route.id, "reply")
    assert _transition(session, route, "engaged", "phase-engaged").outcome == "accepted"
    for observation_type in (
        "requirement_confirmed",
        "specification_confirmed",
        "quantity_or_budget_confirmed",
        "timeline_confirmed",
    ):
        record_observation(session, route.id, observation_type)
    qualified = _transition(session, route, "qualified", "phase-qualified")
    assert len(qualified.evidence_snapshot_json["qualification_types"]) == 4
    for observation_type in ("supplier_quote", "cost_inputs_complete"):
        record_observation(session, route.id, observation_type)
    assert _transition(session, route, "priceable", "phase-priceable").outcome == "accepted"
    for observation_type in ("buyer_quote_approved", "buyer_quote_sent"):
        record_observation(session, route.id, observation_type)
    assert _transition(session, route, "quoted", "phase-quoted").outcome == "accepted"
    record_observation(session, route.id, "negotiation_started")
    assert _transition(session, route, "negotiating", "phase-negotiating").outcome == "accepted"
    record_observation(session, route.id, "purchase_order")
    assert _transition(session, route, "committed", "phase-committed").outcome == "accepted"
    record_observation(session, route.id, "payment_reconciled")
    assert _transition(session, route, "collected", "phase-collected").outcome == "accepted"


def test_execution_commands_reject_naive_business_times():
    naive = datetime.now()
    with pytest.raises(ValueError, match="timezone"):
        ExperimentCreate(
            experiment_key="naive-experiment",
            idempotency_key="naive-experiment",
            question="Is this timestamp valid?",
            hypothesis="It should be rejected.",
            metric_name="validation",
            amount=Decimal("1.00"),
            currency="USD",
            deadline=naive,
            success_condition={"ok": True},
            failure_condition={"failed": True},
            inconclusive_condition={"unknown": True},
        )
    with pytest.raises(ValueError, match="timezone"):
        ActionCreate(
            action_key="naive-action",
            idempotency_key="naive-action",
            action_type="research",
            description="Reject a naive action deadline.",
            amount=Decimal("1.00"),
            currency="USD",
            due_at=naive,
            sla_seconds=60,
        )
    with pytest.raises(ValueError, match="timezone"):
        ObservationCreate(
            idempotency_key="naive-observation",
            observation_type="reply",
            raw_text="Reject a naive observation time.",
            occurred_at=naive,
        )
    with pytest.raises(ValueError, match="timezone"):
        WorkflowJobCreate(
            idempotency_key="naive-workflow",
            job_type="deal.next_action",
            payload={},
            available_at=naive,
            max_attempts=1,
        )


def test_action_observation_and_experiment_guards_fail_closed(session, deal_route_factory):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    with pytest.raises(LookupError):
        ActionService(session).get("missing")
    with pytest.raises(LookupError):
        ActionService(session).create(
            "missing",
            ActionCreate(
                action_key="missing-parent",
                idempotency_key="missing-parent",
                action_type="research",
                description="This parent does not exist.",
                amount=Decimal("1.00"),
                currency="USD",
                due_at=datetime.now(UTC) + timedelta(hours=1),
                sla_seconds=60,
            ),
        )
    with pytest.raises(ValueError, match="currencies"):
        ActionService(session).create(
            experiment.id,
            ActionCreate(
                action_key="wrong-currency",
                idempotency_key="wrong-currency",
                action_type="research",
                description="Currency mismatch fixture.",
                amount=Decimal("1.00"),
                currency="EUR",
                due_at=datetime.now(UTC) + timedelta(hours=1),
                sla_seconds=60,
            ),
        )
    with pytest.raises(ValueError, match="dependency"):
        create_action(
            session,
            experiment.id,
            key="missing-dependency",
            dependencies=["missing-action"],
        )
    pending = create_action(
        session,
        experiment.id,
        key="pending-external",
        external=True,
        policy_status="pending",
        policy_ref="policy:pending",
    )
    approved = ActionService(session).update_policy(
        pending.id,
        ActionPolicyUpdate(
            expected_version=pending.version,
            policy_status="approved",
            policy_decision_ref="policy:approved",
        ),
    )
    with pytest.raises(OptimisticLockError):
        ActionService(session).update_policy(
            pending.id,
            ActionPolicyUpdate(
                expected_version=1,
                policy_status="denied",
                policy_decision_ref="policy:denied",
            ),
        )
    with pytest.raises(ValueError, match="could not be verified"):
        ActionService(session).queue(
            approved.id,
            ActionQueueRequest(expected_version=approved.version, actor="operator"),
        )
    internal = create_action(session, experiment.id, key="not-queued")
    with pytest.raises(ValueError, match="cannot execute"):
        ActionService(session).execute(
            internal.id,
            ActionExecutionRequest(expected_version=internal.version, actor="operator"),
        )
    with pytest.raises(ValueError, match="succeeded"):
        ActionService(session).compensate(
            internal.id,
            ActionCompensationRequest(
                expected_version=internal.version,
                actor="operator",
                reason="Cannot compensate an unexecuted action.",
            ),
        )
    row = ActionService(session)._action(pending.id)
    with pytest.raises(PermissionError):
        InternalNoopExecutor().execute(
            action=row,
            external_effect_key=row.external_effect_key,
            payload={},
        )

    observation_request = ObservationCreate(
        idempotency_key="observation-idempotent",
        experiment_id=experiment.id,
        observation_type="reply",
        raw_text="Raw message is retained.",
        structured_interpretation={"verified": True},
        occurred_at=datetime.now(UTC),
    )
    observations = ObservationService(session)
    first = observations.record(route.id, observation_request)
    assert observations.record(route.id, observation_request).id == first.id
    with pytest.raises(ValueError, match="experiment"):
        observations.record(
            route.id,
            observation_request.model_copy(
                update={
                    "idempotency_key": "observation-wrong-experiment",
                    "experiment_id": "missing",
                }
            ),
        )
    assert observations.list(route.id)

    with pytest.raises(OptimisticLockError):
        ExperimentService(session).start(experiment.id, expected_version=99)
    started = ExperimentService(session).start(experiment.id, expected_version=1)
    close = ExperimentClose(
        idempotency_key="edge-close",
        expected_version=started.version,
        outcome="failed",
        observation_ids=[first.id],
        actor="reviewer",
        reason="The configured failure condition was verified.",
    )
    ExperimentService(session).close(experiment.id, close)
    with pytest.raises(ValueError, match="already ended"):
        ExperimentService(session).close(
            experiment.id,
            close.model_copy(update={"idempotency_key": "edge-close-again", "expected_version": 3}),
        )
    with pytest.raises(LookupError):
        ExperimentService(session).get("missing")
    assert ExperimentService(session).list(route.id)


def test_budget_and_lifecycle_guards_reject_invalid_scope_versions_and_allocations(
    session, deal_route_factory
):
    cell, route = deal_route_factory(cell_budget="600.00", route_budget="300.00")
    experiment = create_experiment(session, route.id, budget="100.00")
    action = create_action(session, experiment.id, cost="20.00")
    budget = BudgetService(session)
    first_decision = budget.authorize(action.id, "edge-budget-decision")
    assert budget.authorize(action.id, "edge-budget-decision").id == first_decision.id
    budget.record_spend(action.id, Decimal("20.00"), actor="operator")
    assert budget.record_spend(action.id, Decimal("20.00"), actor="operator").amount == Decimal(
        "20.0000"
    )
    with pytest.raises(ValueError, match="immutable"):
        budget.record_spend(action.id, Decimal("21.00"), actor="operator")
    with pytest.raises(ValueError, match="scope"):
        budget.adjust(
            "invalid",
            cell.id,
            BudgetAdjustmentRequest(
                idempotency_key="invalid-scope",
                expected_version=1,
                amount=Decimal("1.00"),
                currency="USD",
                approver="finance",
                reason="Invalid scope fixture.",
            ),
        )
    with pytest.raises(ValueError, match="currency"):
        budget.adjust(
            "route",
            route.id,
            BudgetAdjustmentRequest(
                idempotency_key="wrong-budget-currency",
                expected_version=route.version,
                amount=Decimal("300.00"),
                currency="EUR",
                approver="finance",
                reason="Wrong currency fixture.",
            ),
        )
    route_adjustment = budget.adjust(
        "route",
        route.id,
        BudgetAdjustmentRequest(
            idempotency_key="route-budget-increase",
            expected_version=route.version,
            amount=Decimal("350.00"),
            currency="USD",
            approver="finance",
            reason="Increase the route validation envelope.",
        ),
    )
    assert route_adjustment.new_limit == Decimal("350.00")
    with pytest.raises(ValueError, match="parent allocation"):
        budget.adjust(
            "experiment",
            experiment.id,
            BudgetAdjustmentRequest(
                idempotency_key="experiment-over-parent",
                expected_version=experiment.version,
                amount=Decimal("400.00"),
                currency="USD",
                approver="finance",
                reason="Parent allocation ceiling fixture.",
            ),
        )
    cell_adjustment = budget.adjust(
        "cell",
        cell.id,
        BudgetAdjustmentRequest(
            idempotency_key="cell-budget-increase",
            expected_version=cell.version,
            amount=Decimal("700.00"),
            currency="USD",
            approver="finance",
            reason="Increase the aggregate validation envelope.",
        ),
    )
    assert cell_adjustment.new_limit == Decimal("700.00")
    with pytest.raises(ValueError, match="parent allocation"):
        budget.adjust(
            "route",
            route.id,
            BudgetAdjustmentRequest(
                idempotency_key="route-over-parent",
                expected_version=2,
                amount=Decimal("800.00"),
                currency="USD",
                approver="finance",
                reason="Cell allocation ceiling fixture.",
            ),
        )

    lifecycle = RouteLifecycleService(session)
    with pytest.raises(OptimisticLockError):
        lifecycle.pause(
            route.id,
            RouteLifecycleRequest(
                idempotency_key="stale-pause",
                expected_version=1,
                actor="owner",
                reason="Stale version fixture.",
            ),
        )
    route_now = DealRouteService(session).get(route.id)
    with pytest.raises(ValueError, match="exceed"):
        lifecycle.fork(
            route.id,
            RouteForkRequest(
                idempotency_key="oversized-fork",
                expected_version=route_now.version,
                actor="owner",
                reason="Oversized fork fixture.",
                route_key="oversized-fork",
                amount=Decimal("400.00"),
                currency="USD",
            ),
        )
    paused = lifecycle.pause(
        route.id,
        RouteLifecycleRequest(
            idempotency_key="valid-edge-pause",
            expected_version=route_now.version,
            actor="owner",
            reason="Valid pause fixture.",
        ),
    )
    with pytest.raises(ValueError, match="route is paused"):
        ActionService(session).queue(
            action.id,
            ActionQueueRequest(expected_version=action.version, actor="operator"),
        )
    with pytest.raises(ValueError, match="cannot pause"):
        lifecycle.pause(
            route.id,
            RouteLifecycleRequest(
                idempotency_key="double-pause",
                expected_version=paused.version,
                actor="owner",
                reason="Double pause fixture.",
            ),
        )
