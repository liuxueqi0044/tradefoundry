from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradefoundry.deals.actions import ActionService
from tradefoundry.deals.contracts import ActionCreate, ExperimentCreate, ObservationCreate
from tradefoundry.deals.experiments import ExperimentService
from tradefoundry.deals.observations import ObservationService


def create_experiment(
    session,
    route_id: str,
    *,
    key: str = "validate-demand",
    budget: str = "200.00",
    deadline: datetime | None = None,
    on_expiry: str = "close_inconclusive",
):
    return ExperimentService(session).create(
        route_id,
        ExperimentCreate(
            experiment_key=key,
            idempotency_key=f"experiment:{route_id}:{key}",
            question="Will a verified buyer engage with this route?",
            hypothesis="A verified buyer will respond to a bounded probe.",
            metric_name="verified_response",
            amount=Decimal(budget),
            currency="USD",
            deadline=deadline or datetime.now(UTC) + timedelta(days=7),
            on_expiry=on_expiry,
            success_condition={"verified_response": True},
            failure_condition={"explicit_rejection": True},
            inconclusive_condition={"no_response_by_deadline": True},
        ),
    )


def create_action(
    session,
    experiment_id: str,
    *,
    key: str = "prepare-brief",
    cost: str = "10.00",
    external: bool = False,
    policy_status: str = "not_required",
    policy_ref: str | None = None,
    dependencies: list[str] | None = None,
    due_at: datetime | None = None,
):
    return ActionService(session).create(
        experiment_id,
        ActionCreate(
            action_key=key,
            idempotency_key=f"action:{experiment_id}:{key}",
            action_type="buyer_probe" if external else "research",
            description="Execute one bounded validation action.",
            external_side_effect=external,
            amount=Decimal(cost),
            currency="USD",
            policy_status=policy_status,
            policy_decision_ref=policy_ref,
            dependency_action_ids=dependencies or [],
            due_at=due_at or datetime.now(UTC) + timedelta(hours=4),
            sla_seconds=3600,
            payload={"channel": "email"} if external else {"task": "desk research"},
        ),
    )


def record_observation(
    session,
    route_id: str,
    observation_type: str,
    *,
    experiment_id: str | None = None,
    action_id: str | None = None,
):
    return ObservationService(session).record(
        route_id,
        ObservationCreate(
            idempotency_key=f"observation:{route_id}:{observation_type}",
            experiment_id=experiment_id,
            action_id=action_id,
            observation_type=observation_type,
            raw_text=f"Raw verified input for {observation_type}.",
            structured_interpretation={"type": observation_type, "verified": True},
            occurred_at=datetime.now(UTC),
            impact_proposal={"direction": "positive", "requires_review": True},
        ),
    )
