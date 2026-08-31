from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrmView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ScreeningOutcome(StrEnum):
    CLEAR = "clear"
    POSSIBLE_MATCH = "possible_match"
    BLOCKED = "blocked"
    REVIEW = "review"


class MoneyAmount(ControlModel):
    amount: Decimal
    currency: str

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO 4217 code")
        return normalized


class FxQuoteCreate(ControlModel):
    quote_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    base_currency: str
    quote_currency: str
    rate: Decimal = Field(gt=0)
    source_name: str = Field(min_length=1, max_length=160)
    source_uri: str | None = None
    provider_reference: str | None = Field(default=None, max_length=240)
    quoted_at: datetime
    valid_until: datetime | None = None

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return MoneyAmount(amount=0, currency=value).currency

    @model_validator(mode="after")
    def different_pair(self):
        if self.base_currency == self.quote_currency:
            raise ValueError("FX quote currencies must differ")
        if self.valid_until and self.valid_until <= self.quoted_at:
            raise ValueError("valid_until must be after quoted_at")
        return self


class FxQuoteView(OrmView):
    id: str
    quote_key: str
    version_no: int
    base_currency: str
    quote_currency: str
    rate: Decimal
    source_name: str
    source_uri: str | None
    provider_reference: str | None
    quoted_at: datetime
    valid_until: datetime | None
    content_hash: str
    status: str


class MoneyConversionCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    money: MoneyAmount
    target_currency: str
    fx_quote_id: str | None = None
    converted_at: datetime

    @field_validator("target_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return MoneyAmount(amount=0, currency=value).currency


class MoneyConversionView(OrmView):
    id: str
    source_amount: Decimal
    source_currency: str
    target_amount: Decimal
    target_currency: str
    fx_quote_id: str | None
    applied_rate: Decimal
    converted_at: datetime
    source_snapshot_json: dict[str, Any]


class CostDefinitionCreate(ControlModel):
    component_key: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=60)
    allocation_method: str
    ad_valorem_basis: str | None = None
    included_incoterms: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=160)

    @field_validator("allocation_method")
    @classmethod
    def valid_method(cls, value: str) -> str:
        if value not in {"one_time", "per_unit", "per_weight", "ad_valorem"}:
            raise ValueError("unsupported allocation method")
        return value

    @field_validator("included_incoterms")
    @classmethod
    def normalize_incoterms(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().upper() for item in value if item.strip()})

    @model_validator(mode="after")
    def validate_basis(self):
        if self.allocation_method == "ad_valorem" and not self.ad_valorem_basis:
            raise ValueError("ad_valorem components require ad_valorem_basis")
        return self


class CostDefinitionView(OrmView):
    id: str
    component_key: str
    version_no: int
    category: str
    allocation_method: str
    ad_valorem_basis: str | None
    included_incoterms_json: list[str]
    description: str
    status: str


class CostComponentInput(ControlModel):
    definition_id: str
    source_reference: str = Field(min_length=1, max_length=200)
    amount: MoneyAmount | None = None
    rate: Decimal | None = None
    rate_currency: str | None = None
    fx_quote_id: str | None = None
    low_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    high_multiplier: Decimal = Field(default=Decimal("1"), gt=0)

    @model_validator(mode="after")
    def require_amount_or_rate(self):
        if self.amount is None and self.rate is None:
            raise ValueError("component requires amount or rate")
        if self.amount is not None and self.rate is not None:
            raise ValueError("component cannot contain both amount and rate")
        if self.rate is None and self.rate_currency is not None:
            raise ValueError("rate_currency is only valid when rate is used")
        if self.low_multiplier > Decimal("1"):
            raise ValueError("low_multiplier cannot exceed 1")
        if self.high_multiplier < Decimal("1"):
            raise ValueError("high_multiplier cannot be below 1")
        return self

    @field_validator("rate_currency")
    @classmethod
    def valid_rate_currency(cls, value: str | None) -> str | None:
        return None if value is None else MoneyAmount(amount=0, currency=value).currency


class LandedCostCreate(ControlModel):
    scenario_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    route_id: str | None = None
    supplier_quote_id: str | None = None
    currency: str
    quantity: Decimal = Field(gt=0)
    quantity_unit: str = Field(min_length=1, max_length=30)
    gross_weight_kg: Decimal | None = Field(default=None, gt=0)
    incoterm: str = Field(min_length=3, max_length=10)
    destination_country: str = Field(min_length=2, max_length=2)
    goods: MoneyAmount
    goods_fx_quote_id: str | None = None
    components: list[CostComponentInput] = Field(default_factory=list)
    required_component_keys: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    status: str = "estimated"
    calculated_at: datetime
    created_by: str = Field(min_length=1, max_length=160)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return MoneyAmount(amount=0, currency=value).currency

    @field_validator("incoterm")
    @classmethod
    def normalize_incoterm(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("destination_country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"estimated", "confirmed"}:
            raise ValueError("scenario status must be estimated or confirmed")
        return value


class LandedCostLineView(OrmView):
    id: str
    component_key: str
    source_reference: str
    amount_low: Decimal
    amount_base: Decimal
    amount_high: Decimal
    explanation: str


class LandedCostView(OrmView):
    id: str
    scenario_key: str
    version_no: int
    route_id: str | None
    supplier_quote_id: str | None
    currency: str
    quantity: Decimal
    incoterm: str
    destination_country: str
    goods_amount_normalized: Decimal
    total_low: Decimal
    total_base: Decimal
    total_high: Decimal
    assumptions_json: list[str]
    missing_inputs_json: list[str]
    calculator_version: str
    input_hash: str
    status: str


class CashflowEventInput(ControlModel):
    event_key: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=50)
    occurs_on: date
    direction: str
    money: MoneyAmount
    fx_quote_id: str | None = None

    @field_validator("direction")
    @classmethod
    def valid_direction(cls, value: str) -> str:
        if value not in {"inflow", "outflow"}:
            raise ValueError("direction must be inflow or outflow")
        return value

    @model_validator(mode="after")
    def positive_amount(self):
        if self.money.amount < 0:
            raise ValueError("cashflow event amount must be non-negative; use direction")
        return self


class CashflowPlanCreate(ControlModel):
    plan_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    route_id: str | None = None
    scenario_id: str | None = None
    currency: str
    annual_financing_rate: Decimal = Field(default=Decimal("0"), ge=0)
    events: list[CashflowEventInput] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    calculated_at: datetime
    created_by: str = Field(min_length=1, max_length=160)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        return MoneyAmount(amount=0, currency=value).currency


class CashflowPlanView(OrmView):
    id: str
    plan_key: str
    version_no: int
    currency: str
    annual_financing_rate: Decimal
    peak_working_capital: Decimal
    financing_cost: Decimal
    working_capital_days: int
    starts_on: date
    ends_on: date
    assumptions_json: list[str]
    input_hash: str
    calculator_version: str


class CashflowEventView(OrmView):
    id: str
    event_key: str
    event_type: str
    occurs_on: date
    direction: str
    original_amount: Decimal
    original_currency: str
    normalized_amount: Decimal
    fx_quote_id: str | None
    generated: bool
    sequence_no: int


class SensitivityVariable(ControlModel):
    best: Decimal
    base: Decimal
    worst: Decimal
    affects: str

    @field_validator("affects")
    @classmethod
    def valid_affect(cls, value: str) -> str:
        if value not in {"cost", "revenue", "working_capital"}:
            raise ValueError("affects must be cost, revenue or working_capital")
        return value


class SensitivityCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    route_id: str | None = None
    scenario_id: str
    cashflow_plan_id: str
    sale_price: MoneyAmount
    variables: dict[str, SensitivityVariable] = Field(default_factory=dict)


class SensitivityView(OrmView):
    id: str
    currency: str
    variables_json: dict[str, Any]
    best_case_json: dict[str, Any]
    base_case_json: dict[str, Any]
    worst_case_json: dict[str, Any]
    sensitivities_json: list[dict[str, Any]]
    input_hash: str
    calculator_version: str


class CreditAssessmentCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    entity_id: str
    as_of: datetime
    valid_days: int = Field(default=90, ge=1, le=365)
    payment_method: str = Field(min_length=1, max_length=50)
    exposure: MoneyAmount
    completed_trades: int = Field(default=0, ge=0)
    late_trades: int = Field(default=0, ge=0)
    defaulted_trades: int = Field(default=0, ge=0)
    collateral_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    created_by: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def valid_history(self):
        if self.late_trades > self.completed_trades:
            raise ValueError("late trades cannot exceed completed trades")
        if self.defaulted_trades > self.completed_trades:
            raise ValueError("defaulted trades cannot exceed completed trades")
        return self


class CreditAssessmentView(OrmView):
    id: str
    entity_id: str
    as_of: datetime
    valid_until: datetime
    grade: str
    probability_of_default: Decimal
    loss_given_default: Decimal
    expected_loss: Decimal
    credit_limit: Decimal
    currency: str
    factors_json: list[str]
    status: str


class CreditOverrideCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    new_grade: str = Field(min_length=1, max_length=20)
    new_limit: Decimal = Field(ge=0)
    approved_by: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=10)
    evidence_claim_ids: list[str] = Field(min_length=1)


class CreditOverrideView(OrmView):
    id: str
    assessment_id: str
    previous_grade: str
    new_grade: str
    previous_limit: Decimal
    new_limit: Decimal
    approved_by: str
    reason: str
    evidence_claim_ids_json: list[str]


class ComplianceEntryInput(ControlModel):
    external_id: str = Field(min_length=1, max_length=200)
    entry_type: str = Field(min_length=1, max_length=50)
    names: list[str] = Field(default_factory=list)
    identifiers: dict[str, list[str]] = Field(default_factory=dict)
    countries: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)
    effective_from: date | None = None
    effective_to: date | None = None


class DatasetSyncCreate(ControlModel):
    dataset_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    dataset_type: str = Field(min_length=1, max_length=50)
    source_uri: str
    publisher: str = Field(min_length=1, max_length=200)
    published_at: datetime
    effective_from: date | None = None
    effective_to: date | None = None
    license_name: str = Field(min_length=1, max_length=160)
    entries: list[ComplianceEntryInput]


class DatasetSyncFailure(ControlModel):
    dataset_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    source_uri: str
    error_message: str = Field(min_length=1)


class ComplianceDatasetView(OrmView):
    id: str
    dataset_key: str
    version_no: int
    dataset_type: str
    source_uri: str
    publisher: str
    published_at: datetime
    content_hash: str
    license_name: str
    entry_count: int
    status: str


class ComplianceSyncAttemptView(OrmView):
    id: str
    dataset_key: str
    source_uri: str
    previous_active_dataset_id: str | None
    resulting_dataset_id: str | None
    status: str
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class ScreeningCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    entity_id: str
    dataset_id: str | None = None
    names: list[str] = Field(min_length=1)
    identifiers: dict[str, list[str]] = Field(default_factory=dict)
    countries: list[str] = Field(default_factory=list)
    identity_complete: bool = False
    owner_screening_run_ids: list[str] = Field(default_factory=list)
    requested_by: str = Field(min_length=1, max_length=160)


class ScreeningView(OrmView):
    id: str
    entity_id: str
    dataset_id: str
    query_snapshot_json: dict[str, Any]
    outcome: str
    maximum_score: Decimal
    reasons_json: list[str]
    matcher_version: str
    freeze_id: str | None
    screened_at: datetime


class ScreeningMatchView(OrmView):
    id: str
    screening_run_id: str
    entry_id: str
    name_score: Decimal
    identifier_score: Decimal
    country_score: Decimal
    total_score: Decimal
    matched_fields_json: list[str]
    explanation_json: list[str]
    outcome: str


class ProductCodeCandidate(ControlModel):
    code: str = Field(min_length=1, max_length=30)
    confidence: Decimal = Field(ge=0, le=1)
    source_claim_id: str | None = None


class ExportControlCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    product_concept_id: str
    buyer_entity_id: str
    dataset_id: str | None = None
    destination_country: str = Field(min_length=2, max_length=2)
    product_code_candidates: list[ProductCodeCandidate] = Field(min_length=1)
    end_use: str | None = None
    as_of: date


class TradeRequirementCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    product_concept_id: str
    dataset_id: str | None = None
    origin_country: str = Field(min_length=2, max_length=2)
    destination_country: str = Field(min_length=2, max_length=2)
    product_code_candidates: list[ProductCodeCandidate] = Field(min_length=1)
    as_of: date


class ExportControlView(OrmView):
    id: str
    product_concept_id: str
    buyer_entity_id: str
    dataset_id: str
    destination_country: str
    product_code_candidates_json: list[dict[str, Any]]
    end_use: str | None
    restriction_candidates_json: list[dict[str, Any]]
    questions_json: list[str]
    outcome: str
    rule_version: str
    assessed_at: datetime


class TradeRequirementView(OrmView):
    id: str
    product_concept_id: str
    dataset_id: str
    origin_country: str
    destination_country: str
    product_code_candidates_json: list[dict[str, Any]]
    tariff_candidates_json: list[dict[str, Any]]
    certification_candidates_json: list[dict[str, Any]]
    remedy_candidates_json: list[dict[str, Any]]
    assumptions_json: list[str]
    outcome: str
    rule_version: str
    assessed_at: datetime


class PolicyCondition(ControlModel):
    path: str = Field(min_length=1, max_length=200)
    operator: str
    value: Any = None

    @field_validator("operator")
    @classmethod
    def valid_operator(cls, value: str) -> str:
        allowed = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "contains"}
        if value not in allowed:
            raise ValueError("unsupported policy condition operator")
        return value


class PolicyRule(ControlModel):
    rule_key: str = Field(min_length=1, max_length=160)
    priority: int = 0
    actions: list[str] = Field(min_length=1)
    effect: Decision
    conditions: list[PolicyCondition] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)
    obligations: dict[str, Any] = Field(default_factory=dict)


class PolicyBundleCreate(ControlModel):
    bundle_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    backend: str = "local"
    rules: list[PolicyRule] = Field(min_length=1)
    external_revision: str | None = None
    created_by: str = Field(min_length=1, max_length=160)

    @field_validator("backend")
    @classmethod
    def valid_backend(cls, value: str) -> str:
        if value not in {"local", "opa"}:
            raise ValueError("backend must be local or opa")
        return value


class PolicyBundleView(OrmView):
    id: str
    bundle_key: str
    version_no: int
    backend: str
    rules_json: list[dict[str, Any]]
    content_hash: str
    external_revision: str | None
    status: str


class PolicyDecisionCreate(ControlModel):
    bundle_key: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=160)
    actor_roles: list[str] = Field(default_factory=list)
    action: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(min_length=1, max_length=80)
    resource_id: str = Field(min_length=1, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class PolicyDecisionView(OrmView):
    id: str
    bundle_id: str
    actor: str
    actor_roles_json: list[str]
    action: str
    resource_type: str
    resource_id: str
    context_hash: str
    decision: str
    reasons_json: list[str]
    obligations_json: dict[str, Any]
    matched_rule_key: str | None
    policy_version: str
    backend_decision_id: str | None
    evaluated_at: datetime


class CommunicationEvaluate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    contact_id: str
    bundle_key: str
    actor: str = Field(min_length=1, max_length=160)
    actor_roles: list[str] = Field(default_factory=list)
    channel: str
    jurisdiction: str
    purpose: str
    lawful_basis: str | None = None
    retention_deadline: datetime | None = None
    first_contact: bool = True
    as_of: datetime


class CommunicationDecisionView(OrmView):
    id: str
    contact_id: str
    policy_decision_id: str
    channel: str
    jurisdiction: str
    purpose: str
    suppression_ids_json: list[str]
    lawful_basis: str | None
    retention_deadline: datetime | None
    decision: str
    blockers_json: list[str]
    evaluated_at: datetime


class ApprovalRequestCreate(ControlModel):
    policy_decision_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    requester: str = Field(min_length=1, max_length=160)
    params: dict[str, Any]
    subject_refs: list[str] = Field(default_factory=list)
    risk_tier: str = "normal"
    amount: MoneyAmount | None = None
    expires_at: datetime


class ApprovalDecisionCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    approver: str = Field(min_length=1, max_length=160)
    approver_roles: list[str] = Field(min_length=1)
    decision: str
    reason: str = Field(min_length=5)
    evidence_claim_ids: list[str] = Field(default_factory=list)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("approval decision must be approve or reject")
        return value


class ApprovalRequestView(OrmView):
    id: str
    policy_decision_id: str
    requester: str
    action: str
    resource_type: str
    resource_id: str
    params_hash: str
    subject_refs_json: list[str]
    risk_tier: str
    amount: Decimal | None
    currency: str | None
    separation_of_duties: bool
    expires_at: datetime
    status: str
    resolved_at: datetime | None


class ApprovalStepView(OrmView):
    id: str
    approval_request_id: str
    sequence_no: int
    required_role: str
    approvals_required: int
    status: str


class ExecutionTokenIssue(ControlModel):
    approval_request_id: str
    params: dict[str, Any]
    issued_by: str = Field(min_length=1, max_length=160)
    ttl_seconds: int = Field(default=600, ge=1, le=3600)


class ExecutionTokenView(ControlModel):
    token: str
    token_id: str
    action: str
    resource_type: str
    resource_id: str
    params_hash: str
    subject_refs: list[str]
    expires_at: datetime


class ExecutionReservation(ControlModel):
    token: str
    action: str
    resource_type: str
    resource_id: str
    params: dict[str, Any]
    effect_key: str = Field(min_length=1, max_length=200)


class ExecutionConsumption(ControlModel):
    token: str
    effect_key: str = Field(min_length=1, max_length=200)
    execution_reference: str = Field(min_length=1, max_length=240)


class RiskCaseOpen(ControlModel):
    case_key: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    case_type: str = Field(min_length=1, max_length=60)
    severity: str = Field(min_length=1, max_length=30)
    source_reference: str = Field(min_length=1, max_length=200)
    subject_refs: list[str] = Field(min_length=1)
    scopes: list[str] = Field(default_factory=lambda: ["external_action"])
    reason: str = Field(min_length=1)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    opened_by: str = Field(min_length=1, max_length=160)


class FreezeRelease(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    reviewed_by: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=10)
    evidence_claim_ids: list[str] = Field(min_length=1)


class RiskCaseView(OrmView):
    id: str
    case_key: str
    case_type: str
    severity: str
    source_reference: str
    subject_refs_json: list[str]
    status: str
    reason: str
    evidence_claim_ids_json: list[str]
    opened_by: str
    opened_at: datetime
    closed_at: datetime | None


class FreezeView(OrmView):
    id: str
    risk_case_id: str
    subject_ref: str
    scope: str
    reason: str
    active: bool
    created_by: str
    created_at: datetime
    released_at: datetime | None


class FreezeReleaseView(OrmView):
    id: str
    freeze_id: str
    reviewed_by: str
    reason: str
    evidence_claim_ids_json: list[str]
    decision: str
    created_at: datetime


class AuditExportCreate(ControlModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    resource_refs: list[str] = Field(min_length=1)
    from_time: datetime | None = None
    to_time: datetime | None = None
    requested_by: str = Field(min_length=1, max_length=160)
    requester_role: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_window(self):
        if self.from_time and self.to_time and self.to_time < self.from_time:
            raise ValueError("to_time cannot be before from_time")
        return self


class AuditExportView(OrmView):
    id: str
    resource_refs_json: list[str]
    requested_by: str
    requester_role: str
    redaction_profile: str
    package_json: dict[str, Any]
    package_hash: str
    created_at: datetime
