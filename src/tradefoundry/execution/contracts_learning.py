"""Versioned contracts for Board 9 outcome, learning and review boundaries.

The contracts intentionally accept references to upstream snapshots instead of importing
their private tables.  A consumer can therefore replay a learning run without having
the ERP/order adapters installed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradefoundry.execution.common import aware


class LearningContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def aware_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return aware(value)
        return value


class OutcomeBuildRequest(LearningContract):
    route_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=3, max_length=200)
    outcome_cutoff_at: datetime
    status: Literal["success", "failure", "stopped", "no_reply"]
    order_id: str | None = None
    pnl_snapshot_id: str | None = None
    collection_signal_id: str | None = None
    cashflow_plan_id: str | None = None
    milestone_ids: list[str] = Field(default_factory=list)
    shipment_ids: list[str] = Field(default_factory=list)
    quality_case_ids: list[str] = Field(default_factory=list)
    # Timeline is retained as facts, not interpreted as a mutable current route state.
    timeline: dict[str, Any] = Field(default_factory=dict)
    interaction: dict[str, Any] = Field(default_factory=dict)
    qualification: dict[str, Any] = Field(default_factory=dict)
    quote: dict[str, Any] = Field(default_factory=dict)
    commit: dict[str, Any] = Field(default_factory=dict)
    delivery: dict[str, Any] = Field(default_factory=dict)
    collection: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    actual_price: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)
    pnl: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)
    actual_pnl: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)
    peak_capital: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    cycle_days: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    quality: dict[str, Any] = Field(default_factory=dict)
    delay: dict[str, Any] = Field(default_factory=dict)
    refund: dict[str, Any] = Field(default_factory=dict)
    claim: dict[str, Any] = Field(default_factory=dict)
    failed_stage: str | None = Field(default=None, max_length=120)
    reasons: list[str] = Field(default_factory=list)
    human_intervention: bool = False
    exploration_marker: bool = False

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def failure_has_explanation(self):
        if self.status != "success" and not (self.failed_stage or self.reasons):
            raise ValueError(
                "failed, stopped and no_reply outcomes require failed_stage or reasons"
            )
        if self.status == "success" and self.failed_stage:
            raise ValueError("successful outcome cannot have failed_stage")
        return self


class OutcomeView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    route_id: str
    idempotency_key: str
    outcome_cutoff_at: datetime
    status: str
    order_id: str | None
    pnl_snapshot_id: str | None
    collection_signal_id: str | None
    cashflow_plan_id: str | None
    milestone_ids_json: list[str]
    quality_case_ids_json: list[str]
    success: bool
    no_reply: bool
    interaction_json: dict[str, Any]
    qualification_json: dict[str, Any]
    quote_json: dict[str, Any]
    commit_json: dict[str, Any]
    delivery_json: dict[str, Any]
    collection_json: dict[str, Any]
    timeline_json: dict[str, Any]
    currency: str
    actual_price: Decimal | None
    pnl: Decimal | None

    @property
    def actual_pnl(self) -> Decimal | None:
        return self.pnl

    peak_capital: Decimal | None
    days: Decimal | None

    @property
    def cycle_days(self) -> Decimal | None:
        return self.days

    quality_json: dict[str, Any]
    delay_json: dict[str, Any]
    refund_json: dict[str, Any]
    claim_json: dict[str, Any]
    failed_stage: str | None
    reasons_json: list[str]
    human_intervention: bool
    exploration_marker: bool
    created_at: datetime


class PredictionActualRequest(LearningContract):
    outcome_id: str
    idempotency_key: str = Field(min_length=3, max_length=200)
    prediction_cutoff_at: datetime
    score_snapshot_id: str
    probability_estimate_id: str
    board8_cost_snapshot_id: str
    pnl_snapshot_id: str
    predicted_cycle_days: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=4
    )


class PredictionActualView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    outcome_id: str
    idempotency_key: str
    prediction_cutoff_at: datetime
    outcome_cutoff_at: datetime
    score_snapshot_id: str | None
    probability_estimate_id: str | None
    board8_cost_snapshot_id: str | None
    pnl_snapshot_id: str | None
    score_snapshot_json: dict[str, Any]
    probability_estimate: float | None
    cost_snapshot_json: dict[str, Any]
    predicted_cost: Decimal | None
    actual_cost: Decimal | None
    cost_error: Decimal | None
    cycle_error: Decimal | None
    probability_error: float | None
    created_at: datetime


class LearningObservation(LearningContract):
    observation_id: str = Field(min_length=1)
    outcome_id: str
    route_id: str
    observation_cutoff: datetime
    feature_snapshot_id: str
    label: Literal["success", "failure", "no_reply"]
    human_intervention: bool = False
    exploration_marker: bool = False

    @model_validator(mode="after")
    def valid_snapshot_reference(self):
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id is required")
        return self


class LearningDatasetBuildRequest(LearningContract):
    dataset_key: str = Field(min_length=3, max_length=120)
    idempotency_key: str = Field(min_length=3, max_length=200)
    dataset_version: int = Field(default=1, ge=1)
    feature_schema_version: str = Field(default="v1", min_length=1, max_length=80)
    observations: list[LearningObservation] = Field(min_length=1)


class LearningDatasetView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    dataset_key: str
    dataset_version: int
    idempotency_key: str
    feature_schema_version: str
    row_count: int
    label_counts_json: dict[str, int]
    status: str
    created_at: datetime


class LearningDatasetItemView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    dataset_id: str
    observation_id: str
    observation_cutoff: datetime
    feature_snapshot_id: str
    feature_snapshot_json: dict[str, Any]
    feature_as_of: datetime | None
    source_max_available_at: datetime | None
    label: str
    human_intervention: bool
    exploration_marker: bool
    created_at: datetime


class EvaluationRequest(LearningContract):
    dataset_id: str
    idempotency_key: str = Field(min_length=3, max_length=200)
    evaluated_at: datetime
    training_cutoff: datetime
    validation_start: datetime
    validation_end: datetime
    model_name: str = Field(default="challenger", min_length=1, max_length=120)
    baseline_predictions: list[float] = Field(min_length=1)
    challenger_predictions: list[float] = Field(min_length=1)
    labels: list[bool] = Field(min_length=1)
    slices: list[dict[str, Any]] = Field(default_factory=list)
    economic: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    bins: int = Field(default=10, ge=2, le=100)

    @model_validator(mode="after")
    def equal_lengths(self):
        n = len(self.labels)
        if len(self.baseline_predictions) != n or len(self.challenger_predictions) != n:
            raise ValueError("predictions and labels must have equal lengths")
        return self

    @model_validator(mode="after")
    def out_of_time_window(self):
        if (
            not self.training_cutoff
            < self.validation_start
            < self.validation_end
            <= self.evaluated_at
        ):
            raise ValueError("evaluation must use a strict out-of-time validation window")
        return self


class EvaluationReportView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    dataset_id: str | None
    idempotency_key: str
    evaluated_at: datetime
    model_name: str
    sample_count: int
    baseline_json: dict[str, Any]
    challenger_json: dict[str, Any]
    slices_json: list[dict[str, Any]]
    economic_json: dict[str, Any]
    safety_json: dict[str, Any]
    eligible: bool
    status: str
    created_at: datetime


class ReviewProposalRequest(LearningContract):
    idempotency_key: str = Field(min_length=3, max_length=200)
    proposal_type: Literal["lesson", "policy", "template", "ontology", "model"]
    subject_ref: str = Field(min_length=1, max_length=200)
    proposal: dict[str, Any] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=200)


class ReviewProposalView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    idempotency_key: str
    proposal_type: str
    subject_ref: str
    proposal_json: dict[str, Any]
    evidence_refs_json: list[str]
    status: str
    created_by: str
    created_at: datetime


class DashboardSnapshotRequest(LearningContract):
    snapshot_key: str = Field(min_length=3, max_length=120)
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    version: str = Field(default="v1", min_length=1, max_length=80)
    reporting_currency: str = Field(default="USD", min_length=3, max_length=3)
    # Optional fact references for adapters that aggregate the execution ledger.
    invoice_ids: list[str] = Field(default_factory=list)
    pnl_snapshot_ids: list[str] = Field(default_factory=list)
    outcome_ids: list[str] = Field(default_factory=list)
    cashflow_plan_ids: list[str] = Field(default_factory=list)

    @field_validator("reporting_currency")
    @classmethod
    def normalize_reporting_currency(cls, value: str) -> str:
        return value.upper()


class DashboardSnapshotView(LearningContract):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    snapshot_key: str
    idempotency_key: str
    as_of: datetime
    version: str
    sales_json: dict[str, Any]
    contribution_json: dict[str, Any]
    capital_json: dict[str, Any]
    outcomes_json: dict[str, Any]
    drilldown_refs_json: list[str]
    created_at: datetime
