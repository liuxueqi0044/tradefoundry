from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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


class DealCellRow(Base):
    __tablename__ = "deals_cells"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cell_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    issuance_command_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_deal_cell_issuance_commands.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_trade_hypotheses.id", ondelete="RESTRICT"), index=True
    )
    owner: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    budget_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    boundaries_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    command_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DealRouteRow(Base):
    __tablename__ = "deals_routes"
    __table_args__ = (UniqueConstraint("cell_id", "route_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cell_id: Mapped[str] = mapped_column(
        ForeignKey("deals_cells.id", ondelete="RESTRICT"), index=True
    )
    route_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_route_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunity_route_candidates.id", ondelete="RESTRICT"), index=True
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    roles_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stage: Mapped[str] = mapped_column(String(30), default="hypothesized", index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    budget_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    parent_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    merged_into_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StageTransitionRow(Base):
    __tablename__ = "deals_stage_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    from_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRow(Base):
    __tablename__ = "deals_experiments"
    __table_args__ = (UniqueConstraint("route_id", "experiment_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    experiment_key: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    budget_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    on_expiry: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    success_condition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    failure_condition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inconclusive_condition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExperimentOutcomeRow(Base):
    __tablename__ = "deals_experiment_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("deals_experiments.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    observation_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionRow(Base):
    __tablename__ = "deals_actions"
    __table_args__ = (UniqueConstraint("experiment_id", "action_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("deals_experiments.id", ondelete="RESTRICT"), index=True
    )
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    action_key: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    external_side_effect: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    policy_decision_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    policy_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependency_action_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sla_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    external_effect_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ActionAttemptRow(Base):
    __tablename__ = "deals_action_attempts"
    __table_args__ = (UniqueConstraint("action_id", "attempt_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    executor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    external_receipt_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ObservationRow(Base):
    __tablename__ = "deals_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_experiments.id", ondelete="RESTRICT"), index=True
    )
    action_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_interpretation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    external_ref: Mapped[str | None] = mapped_column(String(300), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    impact_proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BudgetAdjustmentRow(Base):
    __tablename__ = "deals_budget_adjustments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    new_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    approver: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BudgetDecisionRow(Base):
    __tablename__ = "deals_budget_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    remaining_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BudgetReservationRow(Base):
    __tablename__ = "deals_budget_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="reserved", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BudgetSpendRow(Base):
    __tablename__ = "deals_budget_spends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("deals_actions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RouteEvidenceLinkRow(Base):
    __tablename__ = "deals_route_evidence_links"
    __table_args__ = (UniqueConstraint("route_id", "observation_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("deals_observations.id", ondelete="RESTRICT"), index=True
    )
    inherited_from_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RouteLifecycleEventRow(Base):
    __tablename__ = "deals_route_lifecycle_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    related_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT")
    )
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowJobRow(Base):
    __tablename__ = "deals_workflow_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ready", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(100), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    wait_reason: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkflowSignalRow(Base):
    __tablename__ = "deals_workflow_signals"
    __table_args__ = (UniqueConstraint("job_id", "signal_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("deals_workflow_jobs.id", ondelete="RESTRICT"), index=True
    )
    signal_key: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
