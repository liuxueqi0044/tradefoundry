from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from moneyed import CurrencyDoesNotExist, get_currency
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RouteStage(StrEnum):
    HYPOTHESIZED = "hypothesized"
    PROBE_READY = "probe_ready"
    PROBING = "probing"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    PRICEABLE = "priceable"
    QUOTED = "quoted"
    NEGOTIATING = "negotiating"
    COMMITTED = "committed"
    COLLECTED = "collected"
    STOPPED = "stopped"


class MoneyContract(BaseModel):
    amount: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        code = value.upper()
        try:
            get_currency(code)
        except CurrencyDoesNotExist as exc:
            raise ValueError(f"unknown ISO currency {code}") from exc
        return code


class DealCellCreate(MoneyContract):
    issuance_command_id: str
    owner: str = Field(min_length=1, max_length=200)


class DealCellView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cell_key: str
    issuance_command_id: str
    hypothesis_id: str
    owner: str
    status: str
    version: int
    budget_limit: Decimal
    currency: str
    boundaries_json: dict[str, Any]
    command_snapshot_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DealCellUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    owner: str = Field(min_length=1, max_length=200)


class DealRouteCreate(MoneyContract):
    route_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    source_route_candidate_id: str
    roles: dict[str, Any] = Field(default_factory=dict)


class DealRouteView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cell_id: str
    route_key: str
    source_route_candidate_id: str | None
    route_type: str
    roles_json: dict[str, Any]
    stage: str
    lifecycle_status: str
    version: int
    budget_limit: Decimal
    currency: str
    parent_route_id: str | None
    merged_into_route_id: str | None
    created_at: datetime
    updated_at: datetime


class StageTransitionRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    expected_version: int = Field(ge=1)
    to_stage: RouteStage
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class StageTransitionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    idempotency_key: str
    from_stage: str
    to_stage: str
    expected_version: int
    outcome: str
    reasons_json: list[str]
    evidence_snapshot_json: dict[str, Any]
    actor: str
    reason: str
    created_at: datetime


class ExperimentCreate(MoneyContract):
    experiment_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    question: str = Field(min_length=3)
    hypothesis: str = Field(min_length=3)
    metric_name: str = Field(min_length=1, max_length=200)
    deadline: datetime
    on_expiry: Literal["close_inconclusive", "escalate"] = "close_inconclusive"
    success_condition: dict[str, Any]
    failure_condition: dict[str, Any]
    inconclusive_condition: dict[str, Any]

    @field_validator("deadline")
    @classmethod
    def aware_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("deadline must include a timezone")
        return value


class ExperimentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    experiment_key: str
    idempotency_key: str
    question: str
    hypothesis: str
    metric_name: str
    budget_limit: Decimal
    currency: str
    deadline: datetime
    on_expiry: str
    status: str
    success_condition_json: dict[str, Any]
    failure_condition_json: dict[str, Any]
    inconclusive_condition_json: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class ExperimentClose(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    expected_version: int = Field(ge=1)
    outcome: Literal["succeeded", "failed", "inconclusive", "escalated"]
    observation_ids: list[str] = Field(default_factory=list)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class ExperimentOutcomeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: str
    idempotency_key: str
    outcome: str
    observation_ids_json: list[str]
    actor: str
    reason: str
    created_at: datetime


class ActionCreate(MoneyContract):
    action_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    action_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=3)
    external_side_effect: bool = False
    policy_decision_ref: str | None = Field(default=None, max_length=200)
    policy_status: Literal["not_required", "pending", "approved", "denied"] = "not_required"
    payload: dict[str, Any] = Field(default_factory=dict)
    dependency_action_ids: list[str] = Field(default_factory=list)
    due_at: datetime
    sla_seconds: int = Field(gt=0, le=2_592_000)

    @field_validator("due_at")
    @classmethod
    def aware_due_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def external_policy_boundary(self):
        if self.external_side_effect and self.policy_status == "not_required":
            raise ValueError("external actions cannot declare policy not required")
        if self.policy_status == "approved" and not self.policy_decision_ref:
            raise ValueError("approved policy status requires policy_decision_ref")
        return self


class ActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: str
    route_id: str
    action_key: str
    idempotency_key: str
    action_type: str
    description: str
    external_side_effect: bool
    estimated_cost: Decimal
    currency: str
    policy_decision_ref: str | None
    policy_status: str
    payload_json: dict[str, Any]
    dependency_action_ids_json: list[str]
    due_at: datetime
    sla_seconds: int
    status: str
    external_effect_key: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ActionExecutionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)
    actual_cost: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)


class ActionQueueRequest(BaseModel):
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)


class ActionPolicyUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    policy_status: Literal["pending", "approved", "denied"]
    policy_decision_ref: str = Field(min_length=1, max_length=200)


class ActionCompensationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class ActionAttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    attempt_no: int
    status: str
    executor_name: str
    error_type: str | None
    error_message: str | None
    external_receipt_json: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class ObservationCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    experiment_id: str | None = None
    action_id: str | None = None
    observation_type: str = Field(min_length=1, max_length=80)
    raw_text: str = Field(min_length=1)
    structured_interpretation: dict[str, Any] = Field(default_factory=dict)
    evidence_claim_id: str | None = None
    external_ref: str | None = Field(default=None, max_length=300)
    occurred_at: datetime
    impact_proposal: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ObservationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    experiment_id: str | None
    action_id: str | None
    idempotency_key: str
    observation_type: str
    raw_text: str
    structured_interpretation_json: dict[str, Any]
    evidence_claim_id: str | None
    external_ref: str | None
    occurred_at: datetime
    impact_proposal_json: dict[str, Any]
    created_at: datetime


class BudgetAdjustmentRequest(MoneyContract):
    idempotency_key: str = Field(min_length=3, max_length=200)
    expected_version: int = Field(ge=1)
    approver: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class BudgetAdjustmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope_type: str
    scope_id: str
    idempotency_key: str
    previous_limit: Decimal
    new_limit: Decimal
    currency: str
    approver: str
    reason: str
    created_at: datetime


class BudgetDecisionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    idempotency_key: str
    decision: str
    requested_amount: Decimal
    currency: str
    remaining_snapshot_json: dict[str, Any]
    reasons_json: list[str]
    created_at: datetime


class RouteLifecycleRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class RouteForkRequest(RouteLifecycleRequest, MoneyContract):
    route_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")


class RouteMergeRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    source_route_id: str
    target_expected_version: int = Field(ge=1)
    source_expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class ExpectedVersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class WorkflowJobCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    job_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]
    available_at: datetime
    max_attempts: int = Field(ge=1, le=100)

    @field_validator("available_at")
    @classmethod
    def aware_available_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("available_at must include a timezone")
        return value


class WorkflowJobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    job_type: str
    payload_json: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_token: str | None
    lease_expires_at: datetime | None
    wait_reason: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowSignalRequest(BaseModel):
    signal_key: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]


class WorkflowClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100)
    lease_seconds: int = Field(default=60, ge=1, le=3600)


class WorkflowLeaseRequest(BaseModel):
    lease_token: str = Field(min_length=1, max_length=200)


class WorkflowFailureRequest(WorkflowLeaseRequest):
    error: str = Field(min_length=1)
    retry_delay_seconds: int = Field(default=30, ge=0, le=86_400)


class WorkflowWaitRequest(WorkflowLeaseRequest):
    reason: str = Field(min_length=1)


class ActionQueueItem(BaseModel):
    action: ActionView
    executable: bool
    blockers: list[str]
    overdue: bool


class TimelineItem(BaseModel):
    at: datetime
    kind: str
    item_id: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class RouteCockpit(BaseModel):
    route: DealRouteView
    experiments: list[ExperimentView]
    observations: list[ObservationView]
    next_actions: list[ActionQueueItem]
    spent: Decimal
    reserved: Decimal
    remaining: Decimal
    blockers: list[str]


class DealCellCockpit(BaseModel):
    cell: DealCellView
    routes: list[RouteCockpit]
    total_spent: Decimal
    total_reserved: Decimal
    remaining: Decimal
    timeline: list[TimelineItem]
