"""Persistence rows owned by the Board 9 learning boundary."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.db import Base
from tradefoundry.execution.common import MONEY, utcnow


class OutcomeRow(Base):
    __tablename__ = "execution_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_order_commands.id", ondelete="RESTRICT"), index=True
    )
    pnl_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_contribution_pnl_snapshots.id", ondelete="RESTRICT"), index=True
    )
    collection_signal_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_collection_signals.id", ondelete="RESTRICT"), index=True
    )
    cashflow_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_cashflow_plans.id", ondelete="RESTRICT"), index=True
    )
    milestone_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    quality_case_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, index=True)
    no_reply: Mapped[bool] = mapped_column(Boolean, index=True)
    timeline_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    interaction_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    qualification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    quote_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    commit_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    delivery_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    collection_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    actual_price: Mapped[Decimal | None] = mapped_column(MONEY)
    pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    peak_capital: Mapped[Decimal | None] = mapped_column(MONEY)
    days: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    delay_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    refund_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    claim_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    failed_stage: Mapped[str | None] = mapped_column(String(120))
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    human_intervention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exploration_marker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PredictionActualRow(Base):
    __tablename__ = "execution_prediction_actuals"
    __table_args__ = (
        UniqueConstraint(
            "outcome_id", "prediction_cutoff_at", name="uq_execution_prediction_outcome_cutoff"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    outcome_id: Mapped[str] = mapped_column(
        ForeignKey("execution_outcomes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    outcome_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    score_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_score_snapshots.id", ondelete="RESTRICT")
    )
    probability_estimate_id: Mapped[str | None] = mapped_column(
        ForeignKey("alpha_probability_estimates.id", ondelete="RESTRICT")
    )
    board8_cost_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_landed_cost_scenarios.id", ondelete="RESTRICT")
    )
    pnl_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_contribution_pnl_snapshots.id", ondelete="RESTRICT")
    )
    score_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    probability_estimate: Mapped[float | None] = mapped_column(Float)
    cost_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    predicted_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    actual_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    cost_error: Mapped[Decimal | None] = mapped_column(MONEY)
    cycle_error: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    probability_error: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningDatasetRow(Base):
    __tablename__ = "execution_learning_datasets"
    __table_args__ = (
        UniqueConstraint("dataset_key", "dataset_version", name="uq_learning_dataset_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_key: Mapped[str] = mapped_column(String(120), index=True)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    label_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningDatasetItemRow(Base):
    __tablename__ = "execution_learning_dataset_items"
    __table_args__ = (
        UniqueConstraint("dataset_id", "observation_id", name="uq_learning_dataset_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_learning_datasets.id", ondelete="RESTRICT"), index=True
    )
    observation_id: Mapped[str] = mapped_column(String(120), index=True)
    outcome_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_outcomes.id", ondelete="RESTRICT"), index=True
    )
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    observation_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    feature_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    feature_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("alpha_feature_snapshots.id", ondelete="RESTRICT"), index=True
    )
    feature_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_max_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    human_intervention: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exploration_marker: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationReportRow(Base):
    __tablename__ = "execution_evaluation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_learning_datasets.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    challenger_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    slices_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    economic_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    safety_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewProposalRow(Base):
    __tablename__ = "execution_review_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(30), index=True)
    subject_ref: Mapped[str] = mapped_column(String(200), index=True)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="review_pending", index=True
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DashboardSnapshotRow(Base):
    __tablename__ = "execution_dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_key", "version", "as_of", name="uq_dashboard_snapshot_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_key: Mapped[str] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    sales_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    contribution_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    capital_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outcomes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    drilldown_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
