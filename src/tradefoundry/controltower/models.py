from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tradefoundry.controltower.common import utcnow
from tradefoundry.db import Base

MONEY = Numeric(19, 4)
RATE = Numeric(24, 12)
QUANTITY = Numeric(19, 6)


class FxQuoteRow(Base):
    __tablename__ = "risk_fx_quotes"
    __table_args__ = (UniqueConstraint("quote_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quote_key: Mapped[str] = mapped_column(String(160), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    base_currency: Mapped[str] = mapped_column(String(3), index=True)
    quote_currency: Mapped[str] = mapped_column(String(3), index=True)
    rate: Mapped[Decimal] = mapped_column(RATE)
    source_name: Mapped[str] = mapped_column(String(160))
    source_uri: Mapped[str | None] = mapped_column(Text)
    provider_reference: Mapped[str | None] = mapped_column(String(240))
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MoneyConversionRow(Base):
    __tablename__ = "risk_money_conversions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    source_amount: Mapped[Decimal] = mapped_column(MONEY)
    source_currency: Mapped[str] = mapped_column(String(3))
    target_amount: Mapped[Decimal] = mapped_column(MONEY)
    target_currency: Mapped[str] = mapped_column(String(3))
    fx_quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_fx_quotes.id", ondelete="RESTRICT"), index=True
    )
    applied_rate: Mapped[Decimal] = mapped_column(RATE)
    converted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostDefinitionRow(Base):
    __tablename__ = "risk_cost_definitions"
    __table_args__ = (UniqueConstraint("component_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    component_key: Mapped[str] = mapped_column(String(120), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(60), index=True)
    allocation_method: Mapped[str] = mapped_column(String(30))
    ad_valorem_basis: Mapped[str | None] = mapped_column(String(60))
    included_incoterms_json: Mapped[list[str]] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LandedCostScenarioRow(Base):
    __tablename__ = "risk_landed_cost_scenarios"
    __table_args__ = (UniqueConstraint("scenario_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_key: Mapped[str] = mapped_column(String(160), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    supplier_quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("bilateral_supplier_quotes.id", ondelete="RESTRICT"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str] = mapped_column(String(30))
    gross_weight_kg: Mapped[Decimal | None] = mapped_column(QUANTITY)
    incoterm: Mapped[str] = mapped_column(String(10), index=True)
    destination_country: Mapped[str] = mapped_column(String(2), index=True)
    goods_amount: Mapped[Decimal] = mapped_column(MONEY)
    goods_currency: Mapped[str] = mapped_column(String(3))
    goods_amount_normalized: Mapped[Decimal] = mapped_column(MONEY)
    total_low: Mapped[Decimal] = mapped_column(MONEY)
    total_base: Mapped[Decimal] = mapped_column(MONEY)
    total_high: Mapped[Decimal] = mapped_column(MONEY)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON)
    missing_inputs_json: Mapped[list[str]] = mapped_column(JSON)
    calculator_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LandedCostLineRow(Base):
    __tablename__ = "risk_landed_cost_lines"
    __table_args__ = (UniqueConstraint("scenario_id", "component_key", "source_reference"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("risk_landed_cost_scenarios.id", ondelete="RESTRICT"), index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("risk_cost_definitions.id", ondelete="RESTRICT"), index=True
    )
    component_key: Mapped[str] = mapped_column(String(120), index=True)
    source_reference: Mapped[str] = mapped_column(String(200))
    original_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    original_currency: Mapped[str | None] = mapped_column(String(3))
    rate_value: Mapped[Decimal | None] = mapped_column(RATE)
    basis_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    amount_low: Mapped[Decimal] = mapped_column(MONEY)
    amount_base: Mapped[Decimal] = mapped_column(MONEY)
    amount_high: Mapped[Decimal] = mapped_column(MONEY)
    fx_quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_fx_quotes.id", ondelete="RESTRICT")
    )
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CashflowPlanRow(Base):
    __tablename__ = "risk_cashflow_plans"
    __table_args__ = (UniqueConstraint("plan_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_key: Mapped[str] = mapped_column(String(160), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    scenario_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_landed_cost_scenarios.id", ondelete="RESTRICT"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3))
    annual_financing_rate: Mapped[Decimal] = mapped_column(RATE)
    peak_working_capital: Mapped[Decimal] = mapped_column(MONEY)
    financing_cost: Mapped[Decimal] = mapped_column(MONEY)
    working_capital_days: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    calculator_version: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CashflowEventRow(Base):
    __tablename__ = "risk_cashflow_events"
    __table_args__ = (UniqueConstraint("plan_id", "event_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("risk_cashflow_plans.id", ondelete="RESTRICT"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    occurs_on: Mapped[date] = mapped_column(Date, index=True)
    direction: Mapped[str] = mapped_column(String(10))
    original_amount: Mapped[Decimal] = mapped_column(MONEY)
    original_currency: Mapped[str] = mapped_column(String(3))
    normalized_amount: Mapped[Decimal] = mapped_column(MONEY)
    fx_quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("risk_fx_quotes.id", ondelete="RESTRICT")
    )
    generated: Mapped[bool] = mapped_column(Boolean, default=False)
    sequence_no: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SensitivityRunRow(Base):
    __tablename__ = "risk_sensitivity_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("deals_routes.id", ondelete="RESTRICT"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("risk_landed_cost_scenarios.id", ondelete="RESTRICT"), index=True
    )
    cashflow_plan_id: Mapped[str] = mapped_column(
        ForeignKey("risk_cashflow_plans.id", ondelete="RESTRICT"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3))
    variables_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    best_case_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    base_case_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    worst_case_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    sensitivities_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    calculator_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditAssessmentRow(Base):
    __tablename__ = "risk_credit_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payment_method: Mapped[str] = mapped_column(String(50))
    exposure_amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    completed_trades: Mapped[int] = mapped_column(Integer)
    late_trades: Mapped[int] = mapped_column(Integer)
    defaulted_trades: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(20), index=True)
    probability_of_default: Mapped[Decimal] = mapped_column(RATE)
    loss_given_default: Mapped[Decimal] = mapped_column(RATE)
    expected_loss: Mapped[Decimal] = mapped_column(MONEY)
    credit_limit: Mapped[Decimal] = mapped_column(MONEY)
    factors_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditOverrideRow(Base):
    __tablename__ = "risk_credit_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("risk_credit_assessments.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    previous_grade: Mapped[str] = mapped_column(String(20))
    new_grade: Mapped[str] = mapped_column(String(20))
    previous_limit: Mapped[Decimal] = mapped_column(MONEY)
    new_limit: Mapped[Decimal] = mapped_column(MONEY)
    approved_by: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComplianceDatasetRow(Base):
    __tablename__ = "risk_compliance_datasets"
    __table_args__ = (UniqueConstraint("dataset_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_key: Mapped[str] = mapped_column(String(160), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    dataset_type: Mapped[str] = mapped_column(String(50), index=True)
    source_uri: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64))
    license_name: Mapped[str] = mapped_column(String(160))
    entry_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComplianceSyncAttemptRow(Base):
    __tablename__ = "risk_compliance_sync_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    dataset_key: Mapped[str] = mapped_column(String(160), index=True)
    source_uri: Mapped[str] = mapped_column(Text)
    previous_active_dataset_id: Mapped[str | None] = mapped_column(String(36))
    resulting_dataset_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ComplianceEntryRow(Base):
    __tablename__ = "risk_compliance_entries"
    __table_args__ = (UniqueConstraint("dataset_id", "external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("risk_compliance_datasets.id", ondelete="RESTRICT"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(200), index=True)
    entry_type: Mapped[str] = mapped_column(String(50), index=True)
    names_json: Mapped[list[str]] = mapped_column(JSON)
    identifiers_json: Mapped[dict[str, list[str]]] = mapped_column(JSON)
    countries_json: Mapped[list[str]] = mapped_column(JSON)
    programs_json: Mapped[list[str]] = mapped_column(JSON)
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScreeningRunRow(Base):
    __tablename__ = "risk_screening_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("risk_compliance_datasets.id", ondelete="RESTRICT"), index=True
    )
    query_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    maximum_score: Mapped[Decimal] = mapped_column(RATE)
    reasons_json: Mapped[list[str]] = mapped_column(JSON)
    matcher_version: Mapped[str] = mapped_column(String(80))
    freeze_id: Mapped[str | None] = mapped_column(String(36), index=True)
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScreeningMatchRow(Base):
    __tablename__ = "risk_screening_matches"
    __table_args__ = (UniqueConstraint("screening_run_id", "entry_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    screening_run_id: Mapped[str] = mapped_column(
        ForeignKey("risk_screening_runs.id", ondelete="RESTRICT"), index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("risk_compliance_entries.id", ondelete="RESTRICT"), index=True
    )
    name_score: Mapped[Decimal] = mapped_column(RATE)
    identifier_score: Mapped[Decimal] = mapped_column(RATE)
    country_score: Mapped[Decimal] = mapped_column(RATE)
    total_score: Mapped[Decimal] = mapped_column(RATE)
    matched_fields_json: Mapped[list[str]] = mapped_column(JSON)
    explanation_json: Mapped[list[str]] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportControlAssessmentRow(Base):
    __tablename__ = "risk_export_control_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    buyer_entity_id: Mapped[str] = mapped_column(
        ForeignKey("master_entities.id", ondelete="RESTRICT"), index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("risk_compliance_datasets.id", ondelete="RESTRICT"), index=True
    )
    destination_country: Mapped[str] = mapped_column(String(2), index=True)
    product_code_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    end_use: Mapped[str | None] = mapped_column(Text)
    restriction_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    questions_json: Mapped[list[str]] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    rule_version: Mapped[str] = mapped_column(String(160))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradeRequirementAssessmentRow(Base):
    __tablename__ = "risk_trade_requirement_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    product_concept_id: Mapped[str] = mapped_column(
        ForeignKey("master_product_concepts.id", ondelete="RESTRICT"), index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("risk_compliance_datasets.id", ondelete="RESTRICT"), index=True
    )
    origin_country: Mapped[str] = mapped_column(String(2))
    destination_country: Mapped[str] = mapped_column(String(2), index=True)
    product_code_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    tariff_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    certification_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    remedy_candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    rule_version: Mapped[str] = mapped_column(String(160))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyBundleRow(Base):
    __tablename__ = "risk_policy_bundles"
    __table_args__ = (UniqueConstraint("bundle_key", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_key: Mapped[str] = mapped_column(String(160), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(30))
    rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    external_revision: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyDecisionRow(Base):
    __tablename__ = "risk_policy_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("risk_policy_bundles.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(160), index=True)
    actor_roles_json: Mapped[list[str]] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    context_hash: Mapped[str] = mapped_column(String(64))
    context_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    reasons_json: Mapped[list[str]] = mapped_column(JSON)
    obligations_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    matched_rule_key: Mapped[str | None] = mapped_column(String(160))
    policy_version: Mapped[str] = mapped_column(String(200))
    backend_decision_id: Mapped[str | None] = mapped_column(String(200))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommunicationDecisionRow(Base):
    __tablename__ = "risk_communication_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("bilateral_contacts.id", ondelete="RESTRICT"), index=True
    )
    policy_decision_id: Mapped[str] = mapped_column(
        ForeignKey("risk_policy_decisions.id", ondelete="RESTRICT"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30))
    jurisdiction: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(60))
    suppression_ids_json: Mapped[list[str]] = mapped_column(JSON)
    lawful_basis: Mapped[str | None] = mapped_column(String(80))
    retention_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str] = mapped_column(String(30), index=True)
    blockers_json: Mapped[list[str]] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalRequestRow(Base):
    __tablename__ = "risk_approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_decision_id: Mapped[str] = mapped_column(
        ForeignKey("risk_policy_decisions.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    requester: Mapped[str] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    params_hash: Mapped[str] = mapped_column(String(64))
    subject_refs_json: Mapped[list[str]] = mapped_column(JSON)
    risk_tier: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    separation_of_duties: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalStepRow(Base):
    __tablename__ = "risk_approval_steps"
    __table_args__ = (UniqueConstraint("approval_request_id", "sequence_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approval_request_id: Mapped[str] = mapped_column(
        ForeignKey("risk_approval_requests.id", ondelete="RESTRICT"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    required_role: Mapped[str] = mapped_column(String(80))
    approvals_required: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalDecisionRow(Base):
    __tablename__ = "risk_approval_decisions"
    __table_args__ = (UniqueConstraint("approval_request_id", "approval_step_id", "approver"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approval_request_id: Mapped[str] = mapped_column(
        ForeignKey("risk_approval_requests.id", ondelete="RESTRICT"), index=True
    )
    approval_step_id: Mapped[str] = mapped_column(
        ForeignKey("risk_approval_steps.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    approver: Mapped[str] = mapped_column(String(160), index=True)
    approver_roles_json: Mapped[list[str]] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionTokenRow(Base):
    __tablename__ = "risk_execution_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approval_request_id: Mapped[str] = mapped_column(
        ForeignKey("risk_approval_requests.id", ondelete="RESTRICT"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    params_hash: Mapped[str] = mapped_column(String(64))
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    subject_refs_json: Mapped[list[str]] = mapped_column(JSON)
    issued_by: Mapped[str] = mapped_column(String(160))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state: Mapped[str] = mapped_column(String(30), index=True)
    reservation_effect_key: Mapped[str | None] = mapped_column(String(200), index=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_reference: Mapped[str | None] = mapped_column(String(240))


class RiskCaseRow(Base):
    __tablename__ = "risk_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    case_type: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    source_reference: Mapped[str] = mapped_column(String(200), index=True)
    subject_refs_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    opened_by: Mapped[str] = mapped_column(String(160))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FreezeRow(Base):
    __tablename__ = "risk_freezes"
    __table_args__ = (UniqueConstraint("risk_case_id", "subject_ref", "scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_case_id: Mapped[str] = mapped_column(
        ForeignKey("risk_cases.id", ondelete="RESTRICT"), index=True
    )
    subject_ref: Mapped[str] = mapped_column(String(200), index=True)
    scope: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FreezeReleaseRow(Base):
    __tablename__ = "risk_freeze_releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    freeze_id: Mapped[str] = mapped_column(
        ForeignKey("risk_freezes.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    reviewed_by: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    evidence_claim_ids_json: Mapped[list[str]] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditExportRow(Base):
    __tablename__ = "risk_audit_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    resource_refs_json: Mapped[list[str]] = mapped_column(JSON)
    from_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str] = mapped_column(String(160))
    requester_role: Mapped[str] = mapped_column(String(80))
    redaction_profile: Mapped[str] = mapped_column(String(80))
    package_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    package_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
