from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.ingestion.models import utcnow

MONEY = Numeric(19, 4)


class FeatureDefinitionRow(Base):
    __tablename__ = "alpha_feature_definitions"
    __table_args__ = (UniqueConstraint("feature_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(120), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_field: Mapped[str] = mapped_column(String(200), nullable=False)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False)
    calculation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    available_time_rule: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureSnapshotRow(Base):
    __tablename__ = "alpha_feature_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    registry_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    sources_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    source_max_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScoringPolicyRow(Base):
    __tablename__ = "alpha_scoring_policies"
    __table_args__ = (UniqueConstraint("policy_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(120), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    weights_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    hard_rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    missing_strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersionRow(Base):
    __tablename__ = "alpha_model_versions"
    __table_args__ = (UniqueConstraint("model_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_key: Mapped[str] = mapped_column(String(120), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(500))
    feature_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    training_data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    validation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    validation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    out_of_time_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    safety_checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScoreSnapshotRow(Base):
    __tablename__ = "alpha_score_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_feature_snapshots.id", ondelete="RESTRICT"), index=True
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_scoring_policies.id", ondelete="RESTRICT"), index=True
    )
    model_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_model_versions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scoring_mode: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    factors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    hard_decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    hard_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    gaps_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sensitivities_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbabilityEstimateRow(Base):
    __tablename__ = "alpha_probability_estimates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    feature_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_feature_snapshots.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estimator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    overall_mean: Mapped[float] = mapped_column(Float, nullable=False)
    overall_low: Mapped[float] = mapped_column(Float, nullable=False)
    overall_high: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CashflowDistributionRow(Base):
    __tablename__ = "alpha_cashflow_distributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    valuation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    discount_rate: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    calculator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RouteValuationRow(Base):
    __tablename__ = "alpha_route_valuations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    probability_estimate_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_probability_estimates.id", ondelete="RESTRICT"), index=True
    )
    cashflow_distribution_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_cashflow_distributions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sunk_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    future_avoidable_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    attention_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    peak_working_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    continuation_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_economic_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    capital_efficiency: Mapped[float] = mapped_column(Float, nullable=False)
    risk_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionValuationRow(Base):
    __tablename__ = "alpha_action_valuations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    route_valuation_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_route_valuations.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    action_cash_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    attention_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    risk_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    expected_post_action_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_voi: Mapped[Decimal] = mapped_column(MONEY, nullable=False, index=True)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    outcomes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskLimitSetRow(Base):
    __tablename__ = "alpha_risk_limit_sets"
    __table_args__ = (UniqueConstraint("limit_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    limit_key: Mapped[str] = mapped_column(String(120), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PortfolioAssessmentRow(Base):
    __tablename__ = "alpha_portfolio_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    limit_set_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_risk_limit_sets.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    feasible: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    violations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    marginal_risk_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AllocationRunRow(Base):
    __tablename__ = "alpha_allocation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    limit_set_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_risk_limit_sets.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    objective_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    total_allocated: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AllocationRow(Base):
    __tablename__ = "alpha_allocations"
    __table_args__ = (UniqueConstraint("run_id", "action_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_allocation_runs.id", ondelete="RESTRICT"), index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    exposure_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BacktestRunRow(Base):
    __tablename__ = "alpha_backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_scoring_policies.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    route_count: Mapped[int] = mapped_column(Integer, nullable=False)
    leakage_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rankings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    baselines_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalibrationReportRow(Base):
    __tablename__ = "alpha_calibration_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_model_versions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    brier_score: Mapped[float | None] = mapped_column(Float)
    ece: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    recommendation: Mapped[str] = mapped_column(String(60), nullable=False)
    overall_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    slices_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelPromotionRow(Base):
    __tablename__ = "alpha_model_promotions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_key: Mapped[str] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    previous_model_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_model_versions.id", ondelete="RESTRICT"), index=True
    )
    target_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_model_versions.id", ondelete="RESTRICT"), index=True
    )
    criteria_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExplorationRunRow(Base):
    __tablename__ = "alpha_exploration_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    allocation_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_allocation_runs.id", ondelete="RESTRICT"), index=True
    )
    model_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_model_versions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total_budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_exploration_rate: Mapped[float] = mapped_column(Float, nullable=False)
    exploration_budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_count: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_outcomes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExplorationSelectionRow(Base):
    __tablename__ = "alpha_exploration_selections"
    __table_args__ = (UniqueConstraint("run_id", "action_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_exploration_runs.id", ondelete="RESTRICT"), index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    propensity: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
