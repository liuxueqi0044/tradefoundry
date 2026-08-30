from datetime import UTC, datetime, timedelta

from deal_helpers import create_action, create_experiment, record_observation
from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session
from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.cockpit import DealCockpitService
from tradefoundry.deals.contracts import ActionExecutionRequest, ActionQueueRequest
from tradefoundry.opportunity.models import RouteCandidateRow


def test_cockpit_aggregates_route_budget_blockers_and_chronological_timeline(
    session, deal_route_factory
):
    cell, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    action = create_action(session, experiment.id)
    record_observation(session, route.id, "reply", experiment_id=experiment.id)
    queued = ActionService(session).queue(
        action.id, ActionQueueRequest(expected_version=action.version, actor="operator")
    )
    ActionService(session).execute(
        action.id,
        ActionExecutionRequest(expected_version=queued.version, actor="operator"),
    )

    cockpit = DealCockpitService(session).cell(cell.id)
    assert cockpit.cell.id == cell.id
    assert cockpit.routes[0].route.id == route.id
    assert cockpit.total_spent > 0
    assert cockpit.remaining < cockpit.cell.budget_limit
    kinds = {item.kind for item in cockpit.timeline}
    assert {
        "stage_transition",
        "experiment",
        "action",
        "action_attempt",
        "observation",
        "budget_decision",
        "budget_spend",
    }.issubset(kinds)
    assert cockpit.timeline == sorted(
        cockpit.timeline, key=lambda item: (item.at, item.item_id), reverse=True
    )


def test_deal_http_contract_exposes_execution_queue_workflow_and_cockpit(
    session, deal_route_factory
):
    cell, route = deal_route_factory()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        assert client.get(f"/v1/deals/cells/{cell.id}").status_code == 200
        owner_update = client.patch(
            f"/v1/deals/cells/{cell.id}/owner",
            json={"expected_version": 1, "owner": "api-deal-owner"},
        )
        assert owner_update.json()["version"] == 2
        assert client.get(f"/v1/deals/cells/{cell.id}/routes").status_code == 200
        assert client.get(f"/v1/deals/routes/{route.id}").status_code == 200
        experiment = client.post(
            f"/v1/deals/routes/{route.id}/experiments",
            json={
                "experiment_key": "api-demand-probe",
                "idempotency_key": "api-demand-probe",
                "question": "Will the buyer respond?",
                "hypothesis": "A bounded probe will receive a response.",
                "metric_name": "verified_response",
                "amount": "100.00",
                "currency": "USD",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
                "success_condition": {"response": True},
                "failure_condition": {"rejected": True},
                "inconclusive_condition": {"timeout": True},
            },
        )
        assert experiment.status_code == 201
        experiment_id = experiment.json()["id"]
        started = client.post(
            f"/v1/deals/experiments/{experiment_id}/start",
            json={"expected_version": 1},
        )
        assert started.json()["status"] == "running"
        assert client.get(f"/v1/deals/routes/{route.id}/experiments").status_code == 200
        action = client.post(
            f"/v1/deals/experiments/{experiment_id}/actions",
            json={
                "action_key": "api-prepare-brief",
                "idempotency_key": "api-prepare-brief",
                "action_type": "research",
                "description": "Prepare a bounded buyer brief.",
                "amount": "10.00",
                "currency": "USD",
                "due_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "sla_seconds": 3600,
            },
        )
        assert action.status_code == 201
        action_id = action.json()["id"]
        queued = client.post(
            f"/v1/deals/actions/{action_id}/queue",
            json={"expected_version": 1, "actor": "api-operator"},
        )
        assert queued.json()["status"] == "queued"
        next_actions = client.get(f"/v1/deals/routes/{route.id}/next-actions")
        assert next_actions.status_code == 200
        executed = client.post(
            f"/v1/deals/actions/{action_id}/execute",
            json={"expected_version": queued.json()["version"], "actor": "api-operator"},
        )
        assert executed.json()["status"] == "succeeded"
        current_action = client.get(f"/v1/deals/routes/{route.id}/actions").json()[0]
        compensated = client.post(
            f"/v1/deals/actions/{action_id}/compensate",
            json={
                "expected_version": current_action["version"],
                "actor": "api-operator",
                "reason": "Verify the API compensation ledger.",
            },
        )
        assert compensated.json()["status"] == "compensated"
        observation = client.post(
            f"/v1/deals/routes/{route.id}/observations",
            json={
                "idempotency_key": "api-reply-observation",
                "experiment_id": experiment_id,
                "action_id": action_id,
                "observation_type": "reply",
                "raw_text": "Buyer replied with a request for details.",
                "structured_interpretation": {"verified": True},
                "occurred_at": datetime.now(UTC).isoformat(),
                "impact_proposal": {"direction": "positive"},
            },
        )
        assert observation.status_code == 201
        assert client.get(f"/v1/deals/routes/{route.id}/observations").status_code == 200
        adjustment = client.post(
            f"/v1/deals/budgets/experiment/{experiment_id}/adjust",
            json={
                "idempotency_key": "api-budget-increase",
                "expected_version": 2,
                "amount": "150.00",
                "currency": "USD",
                "approver": "api-finance-controller",
                "reason": "Allow a second bounded validation cycle.",
            },
        )
        assert adjustment.json()["new_limit"] == "150.00"
        transition = client.post(
            f"/v1/deals/routes/{route.id}/transitions",
            json={
                "idempotency_key": "api-probe-ready",
                "expected_version": 1,
                "to_stage": "probe_ready",
                "actor": "api-operator",
                "reason": "The bounded probe package is complete.",
            },
        )
        assert transition.json()["outcome"] == "accepted"
        closed = client.post(
            f"/v1/deals/experiments/{experiment_id}/close",
            json={
                "idempotency_key": "api-close-experiment",
                "expected_version": 3,
                "outcome": "succeeded",
                "observation_ids": [observation.json()["id"]],
                "actor": "api-reviewer",
                "reason": "Verified reply met the success condition.",
            },
        )
        assert closed.json()["outcome"] == "succeeded"
        assert client.post("/v1/deals/experiments/close-due").status_code == 200
        cockpit = client.get(f"/v1/deals/cells/{cell.id}/cockpit")
        assert cockpit.status_code == 200
        assert cockpit.json()["routes"][0]["route"]["id"] == route.id
        assert client.get(f"/v1/deals/routes/{route.id}/cockpit").status_code == 200
        assert client.get(f"/v1/deals/cells/{cell.id}/timeline").status_code == 200
        assert client.get(f"/v1/deals/cells/{cell.id}/next-actions").status_code == 200

        paused = client.post(
            f"/v1/deals/routes/{route.id}/pause",
            json={
                "idempotency_key": "api-pause-route",
                "expected_version": 2,
                "actor": "api-owner",
                "reason": "Pause before testing a route fork.",
            },
        )
        assert paused.json()["lifecycle_status"] == "paused"
        resumed = client.post(
            f"/v1/deals/routes/{route.id}/resume",
            json={
                "idempotency_key": "api-resume-route",
                "expected_version": paused.json()["version"],
                "actor": "api-owner",
                "reason": "Resume for the route fork test.",
            },
        )
        forked = client.post(
            f"/v1/deals/routes/{route.id}/fork",
            json={
                "idempotency_key": "api-fork-route",
                "expected_version": resumed.json()["version"],
                "actor": "api-owner",
                "reason": "Validate a partner-assisted branch.",
                "route_key": "api-partner-fork",
                "amount": "100.00",
                "currency": "USD",
            },
        )
        assert forked.status_code == 201
        parent_version = client.get(f"/v1/deals/routes/{route.id}").json()["version"]
        merged = client.post(
            f"/v1/deals/routes/{route.id}/merge",
            json={
                "idempotency_key": "api-merge-route",
                "source_route_id": forked.json()["id"],
                "target_expected_version": parent_version,
                "source_expected_version": forked.json()["version"],
                "actor": "api-owner",
                "reason": "The fork is no longer independently useful.",
            },
        )
        terminated = client.post(
            f"/v1/deals/routes/{route.id}/terminate",
            json={
                "idempotency_key": "api-terminate-route",
                "expected_version": merged.json()["version"],
                "actor": "api-owner",
                "reason": "The acceptance route has reached its explicit stop.",
            },
        )
        assert terminated.json()["lifecycle_status"] == "terminated"
        workflow = client.post(
            "/v1/deals/workflows",
            json={
                "idempotency_key": "api-workflow",
                "job_type": "deal.next_action",
                "payload": {"cell_id": cell.id},
                "available_at": datetime.now(UTC).isoformat(),
                "max_attempts": 3,
            },
        )
        assert workflow.status_code == 201
        workflow_id = workflow.json()["id"]
        assert client.get(f"/v1/deals/workflows/{workflow_id}").status_code == 200
        claimed = client.post(
            "/v1/deals/workflows/claim",
            json={"worker_id": "api-worker", "lease_seconds": 60},
        )
        assert claimed.json()["status"] == "running"
        waiting = client.post(
            f"/v1/deals/workflows/{workflow_id}/wait",
            json={
                "lease_token": claimed.json()["lease_token"],
                "reason": "Wait for approval.",
            },
        )
        assert waiting.json()["status"] == "waiting"
        signalled = client.post(
            f"/v1/deals/workflows/{workflow_id}/signals",
            json={"signal_key": "approved", "payload": {"approved": True}},
        )
        assert signalled.json()["status"] == "ready"
        claimed_again = client.post(
            "/v1/deals/workflows/claim",
            json={"worker_id": "api-worker", "lease_seconds": 60},
        ).json()
        failed = client.post(
            f"/v1/deals/workflows/{workflow_id}/fail",
            json={
                "lease_token": claimed_again["lease_token"],
                "error": "retry fixture",
                "retry_delay_seconds": 0,
            },
        )
        assert failed.json()["status"] == "retry"
        final_claim = client.post(
            "/v1/deals/workflows/claim",
            json={"worker_id": "api-worker", "lease_seconds": 60},
        ).json()
        completed = client.post(
            f"/v1/deals/workflows/{workflow_id}/complete",
            json={"lease_token": final_claim["lease_token"]},
        )
        assert completed.json()["status"] == "completed"
        assert client.get("/v1/deals/cells/missing").status_code == 404
        assert len(app.openapi()["paths"]) >= 100
    finally:
        app.dependency_overrides.clear()


def test_deal_http_creation_contract_and_conflicts(session, ready_issuance_factory):
    issuance, hypothesis = ready_issuance_factory()
    candidate = next(
        session.get(RouteCandidateRow, candidate_id)
        for candidate_id in hypothesis.route_candidate_ids_json
        if session.get(RouteCandidateRow, candidate_id).feasibility == "feasible"
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        created = client.post(
            "/v1/deals/cells",
            json={
                "issuance_command_id": issuance.id,
                "owner": "api-creation-owner",
                "amount": "300.00",
                "currency": "USD",
            },
        )
        assert created.status_code == 201
        cell_id = created.json()["id"]
        route = client.post(
            f"/v1/deals/cells/{cell_id}/routes",
            json={
                "route_key": "api-created-route",
                "source_route_candidate_id": candidate.id,
                "roles": {"owner": "api-creation-owner"},
                "amount": "200.00",
                "currency": "USD",
            },
        )
        assert route.status_code == 201
        assert (
            client.post(
                "/v1/deals/cells",
                json={
                    "issuance_command_id": issuance.id,
                    "owner": "conflicting-owner",
                    "amount": "300.00",
                    "currency": "USD",
                },
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/v1/deals/cells/{cell_id}/owner",
                json={"expected_version": 99, "owner": "stale-owner"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/v1/deals/cells/{cell_id}/routes",
                json={
                    "route_key": "api-over-budget-route",
                    "source_route_candidate_id": candidate.id,
                    "amount": "200.00",
                    "currency": "USD",
                },
            ).status_code
            == 409
        )
        assert client.get("/v1/deals/cells/missing/routes").status_code == 404
        assert client.get("/v1/deals/routes/missing").status_code == 404
    finally:
        app.dependency_overrides.clear()
