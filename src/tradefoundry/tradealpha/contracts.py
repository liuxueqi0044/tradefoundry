from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from moneyed import CurrencyDoesNotExist, get_currency
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CurrencyAmount(BaseModel):
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


class AwareTimeModel(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def datetimes_must_be_aware(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("business and availability times must include a timezone")
        return value


class FeatureDefinitionCreate(BaseModel):
    feature_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    source_kind: Literal["claim", "entity", "event", "hypothesis", "deal", "outcome", "derived"]
    source_field: str = Field(min_length=1, max_length=200)
    value_type: Literal["number", "boolean", "category", "count", "ratio"]
    calculation_ref: str = Field(min_length=3, max_length=160)
    available_time_rule: Literal[
        "created_at", "recorded_at", "occurred_and_recorded", "manual_snapshot"
    ]
    description: str = Field(min_length=3)
    created_by: str = Field(min_length=1, max_length=200)


class FeatureDefinitionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    feature_key: str
    version_no: int
    idempotency_key: str
    source_kind: str
    source_field: str
    value_type: str
    calculation_ref: str
    available_time_rule: str
    description: str
    status: str
    created_by: str
    created_at: datetime


class FeatureSnapshotRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime


class FeatureSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    idempotency_key: str
    as_of: datetime
    registry_hash: str
    features_json: dict[str, Any]
    sources_json: dict[str, Any]
    context_json: dict[str, Any]
    completeness: float
    source_max_available_at: datetime
    created_at: datetime


class HardRule(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"]
    value: Any
    reason: str = Field(min_length=3)


class ScoringPolicyCreate(BaseModel):
    policy_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    name: str = Field(min_length=3, max_length=240)
    weights: dict[str, float]
    hard_rules: list[HardRule] = Field(default_factory=list)
    missing_strategy: Literal["zero", "neutral", "veto"] = "neutral"
    created_by: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_weights(self):
        if not self.weights:
            raise ValueError("at least one scoring weight is required")
        if any(not -10 <= value <= 10 for value in self.weights.values()):
            raise ValueError("scoring weights must be between -10 and 10")
        if sum(abs(value) for value in self.weights.values()) == 0:
            raise ValueError("scoring weights cannot all be zero")
        return self


class ScoringPolicyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_key: str
    version_no: int
    idempotency_key: str
    name: str
    status: str
    weights_json: dict[str, float]
    hard_rules_json: list[dict[str, Any]]
    missing_strategy: str
    created_by: str
    created_at: datetime


class ScoreRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    feature_snapshot_id: str
    policy_id: str
    as_of: datetime
    model_version_id: str | None = None


class ScoreSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    feature_snapshot_id: str
    policy_id: str
    model_version_id: str | None
    idempotency_key: str
    as_of: datetime
    scoring_mode: str
    factors_json: list[dict[str, Any]]
    total_score: float
    hard_decision: str
    hard_reasons_json: list[str]
    assumptions_json: list[str]
    gaps_json: list[str]
    sensitivities_json: list[dict[str, Any]]
    created_at: datetime


class BetaPrior(BaseModel):
    alpha: float = Field(gt=0, le=1000)
    beta: float = Field(gt=0, le=1000)


class ProbabilityEstimateRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    feature_snapshot_id: str | None = None
    priors: dict[str, BetaPrior] = Field(default_factory=dict)
    interval_mass: float = Field(default=0.9, gt=0.5, lt=1)
    seed: int = Field(default=20260831, ge=0, le=2_147_483_647)


class ProbabilityEstimateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    feature_snapshot_id: str | None
    idempotency_key: str
    as_of: datetime
    estimator_version: str
    context_json: dict[str, Any]
    stages_json: list[dict[str, Any]]
    overall_mean: float
    overall_low: float
    overall_high: float
    sample_size: int
    created_at: datetime


class TriangularCashflow(AwareTimeModel):
    low: Decimal = Field(max_digits=19, decimal_places=4)
    mode: Decimal = Field(max_digits=19, decimal_places=4)
    high: Decimal = Field(max_digits=19, decimal_places=4)
    at: datetime

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.mode <= self.high:
            raise ValueError("cashflow band must satisfy low <= mode <= high")
        return self


class LossDistribution(BaseModel):
    probability: float = Field(ge=0, le=1)
    severity: TriangularCashflow


class CashflowDistributionRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    valuation_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    discount_rate: float = Field(ge=-0.5, le=2)
    revenue: TriangularCashflow
    variable_cost: TriangularCashflow
    credit_loss: LossDistribution
    quality_loss: LossDistribution
    compliance_loss: LossDistribution
    sample_count: int = Field(default=2000, ge=100, le=100_000)
    seed: int = Field(default=20260831, ge=0, le=2_147_483_647)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return CurrencyAmount(amount=0, currency=value).currency


class CashflowDistributionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    idempotency_key: str
    valuation_at: datetime
    currency: str
    discount_rate: float
    sample_count: int
    seed: int
    inputs_json: dict[str, Any]
    metrics_json: dict[str, Any]
    calculator_version: str
    created_at: datetime


class RouteValuationRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    probability_estimate_id: str
    cashflow_distribution_id: str
    as_of: datetime
    peak_working_capital: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    attention_hours: Decimal = Field(ge=0, max_digits=12, decimal_places=4)
    attention_hourly_cost: Decimal = Field(ge=0, max_digits=19, decimal_places=4)


class RouteValuationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    route_id: str
    probability_estimate_id: str
    cashflow_distribution_id: str
    idempotency_key: str
    as_of: datetime
    currency: str
    sunk_cost: Decimal
    future_avoidable_cost: Decimal
    attention_cost: Decimal
    peak_working_capital: Decimal
    continuation_value: Decimal
    total_economic_value: Decimal
    capital_efficiency: float
    risk_metrics_json: dict[str, Any]
    assumptions_json: list[str]
    created_at: datetime


class ActionOutcomeScenario(BaseModel):
    outcome_key: str = Field(min_length=1, max_length=100)
    probability: float = Field(ge=0, le=1)
    post_action_route_value: Decimal = Field(max_digits=19, decimal_places=4)


class ActionValuationRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    route_valuation_id: str
    as_of: datetime
    attention_cost: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    legal_reputation_risk_cost: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    outcomes: list[ActionOutcomeScenario] = Field(min_length=2)

    @model_validator(mode="after")
    def probabilities_sum_to_one(self):
        if abs(sum(item.probability for item in self.outcomes) - 1) > 1e-9:
            raise ValueError("action outcome probabilities must sum to one")
        return self


class ActionValuationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    route_valuation_id: str
    idempotency_key: str
    as_of: datetime
    currency: str
    action_cash_cost: Decimal
    attention_cost: Decimal
    risk_cost: Decimal
    expected_post_action_value: Decimal
    net_voi: Decimal
    priority_score: float
    recommended: bool
    outcomes_json: list[dict[str, Any]]
    created_at: datetime


class RiskLimits(BaseModel):
    country: dict[str, Decimal] = Field(default_factory=dict)
    buyer: dict[str, Decimal] = Field(default_factory=dict)
    product: dict[str, Decimal] = Field(default_factory=dict)
    currency: dict[str, Decimal] = Field(default_factory=dict)
    correlation_group: dict[str, Decimal] = Field(default_factory=dict)
    unsecured_credit: Decimal = Field(default=Decimal(0), ge=0)


class RiskLimitSetCreate(CurrencyAmount):
    limit_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    limits: RiskLimits
    created_by: str = Field(min_length=1, max_length=200)


class RiskLimitSetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    limit_key: str
    version_no: int
    idempotency_key: str
    currency: str
    total_budget: Decimal
    limits_json: dict[str, Any]
    status: str
    created_by: str
    created_at: datetime


class PortfolioCandidate(CurrencyAmount):
    route_id: str
    action_id: str
    score: float
    country_code: str
    buyer_id: str
    product_id: str
    correlation_group: str
    unsecured_credit: Decimal = Field(default=Decimal(0), ge=0)
    policy_clear: bool
    risk_tier: Literal["low", "normal", "high", "critical"] = "normal"


class PortfolioAssessmentRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    candidates: list[PortfolioCandidate]


class PortfolioAssessmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    limit_set_id: str
    idempotency_key: str
    as_of: datetime
    candidates_json: list[dict[str, Any]]
    feasible: bool
    violations_json: list[dict[str, Any]]
    marginal_risk_json: list[dict[str, Any]]
    created_at: datetime


class AllocationRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    budget: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3)
    candidates: list[PortfolioCandidate]

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return CurrencyAmount(amount=0, currency=value).currency


class AllocationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    route_id: str
    action_id: str
    rank: int
    requested_amount: Decimal
    allocated_amount: Decimal
    status: str
    score: float
    reasons_json: list[str]
    exposure_json: dict[str, Any]
    created_at: datetime


class AllocationRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    limit_set_id: str
    idempotency_key: str
    as_of: datetime
    budget: Decimal
    currency: str
    objective_version: str
    status: str
    candidates_json: list[dict[str, Any]]
    total_allocated: Decimal
    metrics_json: dict[str, Any]
    created_at: datetime


class AllocationResult(BaseModel):
    run: AllocationRunView
    allocations: list[AllocationView]


class BacktestLabel(AwareTimeModel):
    route_id: str
    outcome: bool
    outcome_available_at: datetime
    manual_baseline_score: float = 0


class BacktestRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    cutoff_at: datetime
    top_k: int = Field(ge=1, le=10_000)
    seed: int = Field(default=20260831, ge=0, le=2_147_483_647)
    feature_snapshot_ids: list[str] = Field(min_length=1)
    labels: list[BacktestLabel]


class BacktestRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_id: str
    idempotency_key: str
    cutoff_at: datetime
    top_k: int
    seed: int
    route_count: int
    leakage_count: int
    metrics_json: dict[str, Any]
    rankings_json: dict[str, Any]
    baselines_json: dict[str, Any]
    created_at: datetime


class CalibrationPoint(AwareTimeModel):
    prediction: float = Field(ge=0, le=1)
    outcome: bool
    prediction_at: datetime
    outcome_at: datetime
    country_code: str = "unknown"
    product_id: str = "unknown"

    @model_validator(mode="after")
    def outcome_after_prediction(self):
        if self.outcome_at <= self.prediction_at:
            raise ValueError("outcome must become available after prediction")
        return self


class CalibrationRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    evaluated_at: datetime
    window_start: datetime
    window_end: datetime
    model_version_id: str | None = None
    points: list[CalibrationPoint]
    bins: int = Field(default=10, ge=2, le=100)
    minimum_samples: int = Field(default=30, ge=1)
    max_brier: float = Field(default=0.25, ge=0, le=1)
    max_ece: float = Field(default=0.1, ge=0, le=1)
    max_mean_prediction_drift: float = Field(default=0.15, ge=0, le=1)
    reference_mean_prediction: float | None = Field(default=None, ge=0, le=1)


class CalibrationReportView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_version_id: str | None
    idempotency_key: str
    evaluated_at: datetime
    window_start: datetime
    window_end: datetime
    sample_count: int
    brier_score: float | None
    ece: float | None
    status: str
    recommendation: str
    overall_json: dict[str, Any]
    slices_json: list[dict[str, Any]]
    thresholds_json: dict[str, Any]
    created_at: datetime


class ModelVersionCreate(AwareTimeModel):
    model_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    model_type: Literal["rule_baseline", "bayesian", "calibrated_ml", "bandit"]
    artifact_uri: str | None = Field(default=None, max_length=500)
    feature_schema_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_data_cutoff: datetime
    validation_start: datetime
    validation_end: datetime
    metrics: dict[str, Any]
    out_of_time_metrics: dict[str, Any]
    safety_checks: dict[str, Any]
    created_by: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def temporal_split(self):
        if not self.training_data_cutoff < self.validation_start < self.validation_end:
            raise ValueError("model validation must be strictly out of time")
        if self.model_type != "rule_baseline" and not self.artifact_uri:
            raise ValueError("trained model versions require an artifact URI")
        return self


class ModelVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_key: str
    version_no: int
    idempotency_key: str
    model_type: str
    artifact_uri: str | None
    feature_schema_hash: str
    training_data_cutoff: datetime
    validation_start: datetime
    validation_end: datetime
    metrics_json: dict[str, Any]
    out_of_time_metrics_json: dict[str, Any]
    safety_checks_json: dict[str, Any]
    created_by: str
    created_at: datetime


class PromotionCriteria(BaseModel):
    minimum_samples: int = Field(default=100, ge=1)
    max_brier: float = Field(default=0.25, ge=0, le=1)
    max_ece: float = Field(default=0.1, ge=0, le=1)
    require_safety_pass: bool = True


class ModelPromotionRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    target_model_version_id: str
    action: Literal["promote", "rollback"] = "promote"
    criteria: PromotionCriteria = Field(default_factory=PromotionCriteria)
    actor: str = Field(min_length=1, max_length=200)


class ModelPromotionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_key: str
    idempotency_key: str
    action: str
    previous_model_version_id: str | None
    target_model_version_id: str
    criteria_json: dict[str, Any]
    decision: str
    reasons_json: list[str]
    actor: str
    created_at: datetime


class ExplorationCandidate(CurrencyAmount):
    route_id: str
    action_id: str
    base_score: float = Field(ge=0)
    policy_clear: bool
    risk_tier: Literal["low", "normal", "high", "critical"]


class ExplorationRequest(AwareTimeModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    allocation_run_id: str | None = None
    model_version_id: str | None = None
    total_budget: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3)
    max_exploration_rate: float = Field(default=0.05, ge=0, le=0.1)
    seed: int = Field(default=20260831, ge=0, le=2_147_483_647)
    outcome_count: int = Field(ge=0)
    minimum_outcomes: int = Field(default=100, ge=1)
    candidates: list[ExplorationCandidate]

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return CurrencyAmount(amount=0, currency=value).currency


class ExplorationSelectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    route_id: str
    action_id: str
    amount: Decimal
    propensity: float
    rank: int
    reason: str
    created_at: datetime


class ExplorationRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    allocation_run_id: str | None
    model_version_id: str | None
    idempotency_key: str
    as_of: datetime
    total_budget: Decimal
    max_exploration_rate: float
    exploration_budget: Decimal
    seed: int
    outcome_count: int
    minimum_outcomes: int
    status: str
    reasons_json: list[str]
    created_at: datetime


class ExplorationResult(BaseModel):
    run: ExplorationRunView
    selections: list[ExplorationSelectionView]


class ScoreExplanation(BaseModel):
    score: ScoreSnapshotView
    why_high_or_low: list[str]
    hard_constraints: list[str]
    assumptions: list[str]
    evidence_gaps: list[str]
    sensitivities: list[dict[str, Any]]
    most_valuable_new_evidence: list[str]
