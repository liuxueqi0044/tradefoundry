from datetime import UTC, datetime, timedelta

import pytest

from tradefoundry.deals.contracts import WorkflowJobCreate, WorkflowSignalRequest
from tradefoundry.deals.workflow import DatabaseWorkflowAdapter


def _job_request(key: str, *, max_attempts: int = 3):
    return WorkflowJobCreate(
        idempotency_key=key,
        job_type="deal.next_action",
        payload={"route_id": "route-1"},
        available_at=datetime.now(UTC) - timedelta(seconds=1),
        max_attempts=max_attempts,
    )


def test_database_workflow_survives_wait_signal_and_worker_reclaim(session):
    adapter = DatabaseWorkflowAdapter(session)
    request = _job_request("workflow-wait-signal")
    job = adapter.enqueue(request)
    assert adapter.enqueue(request).id == job.id
    claimed = adapter.claim_due("worker-a", lease_seconds=60)
    assert claimed.id == job.id
    waiting = adapter.wait(claimed.id, claimed.lease_token, "Awaiting PolicyDecision")
    assert waiting.status == "waiting"
    signalled = adapter.signal(
        job.id,
        WorkflowSignalRequest(
            signal_key="policy-approved",
            payload={"decision_ref": "policy:1"},
        ),
    )
    assert signalled.status == "ready"
    repeated = adapter.signal(
        job.id,
        WorkflowSignalRequest(
            signal_key="policy-approved",
            payload={"decision_ref": "policy:1"},
        ),
    )
    assert repeated.id == job.id
    reclaimed = adapter.claim_due("worker-b", lease_seconds=60)
    assert reclaimed.attempts == 2
    completed = adapter.complete(job.id, reclaimed.lease_token)
    assert completed.status == "completed"
    assert adapter.claim_due("worker-c") is None
    assert adapter.list_signals(job.id)[0]["signal_key"] == "policy-approved"


def test_database_workflow_retries_dies_and_rejects_stale_leases(session):
    adapter = DatabaseWorkflowAdapter(session)
    job = adapter.enqueue(_job_request("workflow-retry", max_attempts=2))
    first = adapter.claim_due("worker-a", lease_seconds=60)
    retry = adapter.fail(
        job.id,
        first.lease_token,
        "temporary failure",
        retry_delay_seconds=0,
    )
    assert retry.status == "retry"
    second = adapter.claim_due("worker-b", lease_seconds=60)
    with pytest.raises(ValueError, match="stale"):
        adapter.complete(job.id, first.lease_token)
    dead = adapter.fail(
        job.id,
        second.lease_token,
        "permanent failure",
        retry_delay_seconds=0,
    )
    assert dead.status == "dead"
    assert adapter.claim_due("worker-c") is None


def test_expired_running_lease_can_be_claimed_after_process_restart(session):
    adapter = DatabaseWorkflowAdapter(session)
    now = datetime.now(UTC)
    job = adapter.enqueue(_job_request("workflow-restart"))
    first = adapter.claim_due("old-process", lease_seconds=1, as_of=now)
    reclaimed = adapter.claim_due("new-process", lease_seconds=60, as_of=now + timedelta(seconds=2))
    assert reclaimed.id == job.id
    assert reclaimed.lease_token != first.lease_token
    assert reclaimed.attempts == 2
