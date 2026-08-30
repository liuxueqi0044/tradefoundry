from decimal import Decimal

import pytest
from deal_helpers import create_action, create_experiment, record_observation
from sqlalchemy import func, select

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.budgets import BudgetService
from tradefoundry.deals.contracts import (
    ActionCompensationRequest,
    ActionExecutionRequest,
    ActionQueueRequest,
    BudgetAdjustmentRequest,
)
from tradefoundry.deals.models import ActionAttemptRow, BudgetSpendRow, DealRouteRow


class ApprovePolicy:
    def is_approved(self, decision_ref, action):
        return decision_ref == "policy:approved" and action.external_side_effect


class FailOnceExecutor:
    name = "fail-once-fixture"

    def __init__(self):
        self.keys = []

    def execute(self, *, action, external_effect_key, payload):
        self.keys.append(external_effect_key)
        if len(self.keys) == 1:
            raise TimeoutError("transient channel timeout")
        return {"external_ref": "provider-message-1", "effect_key": external_effect_key}

    def compensate(self, *, action, external_effect_key, reason):
        return {"compensated": True, "effect_key": external_effect_key, "reason": reason}


def test_action_ledger_is_retryable_idempotent_and_compensatable(session, deal_route_factory):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    action = create_action(
        session,
        experiment.id,
        key="send-bounded-probe",
        cost="25.00",
        external=True,
        policy_status="approved",
        policy_ref="policy:approved",
    )
    executor = FailOnceExecutor()
    service = ActionService(session, policy_port=ApprovePolicy(), executor=executor)
    queued = service.queue(action.id, ActionQueueRequest(expected_version=1, actor="operator"))
    with pytest.raises(TimeoutError, match="transient"):
        service.execute(
            action.id,
            ActionExecutionRequest(expected_version=queued.version, actor="operator"),
        )
    failed = service.get(action.id)
    retried = service.queue(
        action.id,
        ActionQueueRequest(expected_version=failed.version, actor="operator"),
    )
    succeeded = service.execute(
        action.id,
        ActionExecutionRequest(expected_version=retried.version, actor="operator"),
    )
    repeated = service.execute(
        action.id,
        ActionExecutionRequest(expected_version=1, actor="operator"),
    )

    assert repeated.id == succeeded.id
    assert executor.keys[0] == executor.keys[1]
    assert session.scalar(select(func.count()).select_from(ActionAttemptRow)) == 2
    assert session.scalar(select(func.count()).select_from(BudgetSpendRow)) == 1
    current = service.get(action.id)
    compensated = service.compensate(
        action.id,
        ActionCompensationRequest(
            expected_version=current.version,
            actor="operator",
            reason="The provider accepted a bounded rollback.",
        ),
    )
    assert compensated.status == "compensated"
    assert service.get(action.id).status == "compensated"


def test_observation_preserves_raw_and_structured_data_without_mutating_route_state(
    session, deal_route_factory
):
    _, route = deal_route_factory()
    experiment = create_experiment(session, route.id)
    before = session.get(DealRouteRow, route.id)
    stage_before, version_before = before.stage, before.version
    observation = record_observation(session, route.id, "reply", experiment_id=experiment.id)
    after = session.get(DealRouteRow, route.id)
    assert observation.raw_text.startswith("Raw verified")
    assert observation.structured_interpretation_json["verified"] is True
    assert observation.impact_proposal_json["requires_review"] is True
    assert (after.stage, after.version) == (stage_before, version_before)


def test_hierarchical_budget_guards_reservations_spend_and_approved_adjustments(
    session, deal_route_factory
):
    cell, route = deal_route_factory(cell_budget="500.00", route_budget="250.00")
    experiment = create_experiment(session, route.id, budget="100.00")
    too_large = create_action(session, experiment.id, key="over-budget", cost="120.00")
    with pytest.raises(ValueError, match="over budget"):
        ActionService(session).queue(
            too_large.id,
            ActionQueueRequest(expected_version=too_large.version, actor="operator"),
        )

    action = create_action(session, experiment.id, key="within-budget", cost="60.00")
    queued = ActionService(session).queue(
        action.id, ActionQueueRequest(expected_version=action.version, actor="operator")
    )
    assert queued.status == "queued"
    spent, reserved = BudgetService(session).usage("experiment", experiment.id)
    assert (spent, reserved) == (Decimal("0"), Decimal("60.0000"))
    with pytest.raises(ValueError, match="below committed"):
        BudgetService(session).adjust(
            "experiment",
            experiment.id,
            BudgetAdjustmentRequest(
                idempotency_key="reduce-below-reservation",
                expected_version=experiment.version,
                amount=Decimal("50.00"),
                currency="USD",
                approver="finance-controller",
                reason="Attempt an invalid budget reduction.",
            ),
        )
    adjustment = BudgetService(session).adjust(
        "experiment",
        experiment.id,
        BudgetAdjustmentRequest(
            idempotency_key="increase-experiment-budget",
            expected_version=experiment.version,
            amount=Decimal("150.00"),
            currency="USD",
            approver="finance-controller",
            reason="Approve more validation capacity.",
        ),
    )
    assert adjustment.previous_limit == Decimal("100.0000")
    assert adjustment.new_limit == Decimal("150.00")
    assert cell.currency == route.currency == adjustment.currency
