from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from moneyed import CurrencyDoesNotExist, get_currency
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrmView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SupplierKind(StrEnum):
    FACTORY = "factory"
    TRADER = "trader"
    AGENT = "agent"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Channel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    PORTAL = "portal"
    MEETING = "meeting"


INCOTERMS_2020 = {"EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"}


def _currency(value: str) -> str:
    code = value.upper()
    try:
        get_currency(code)
    except CurrencyDoesNotExist as exc:
        raise ValueError(f"unknown ISO currency {code}") from exc
    return code


def _country(value: str) -> str:
    code = value.upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("country must be an ISO alpha-2 code")
    return code


def _incoterm(value: str | None) -> str | None:
    if value is None:
        return None
    term = value.upper()
    if term not in INCOTERMS_2020:
        raise ValueError(f"unsupported Incoterms 2020 code {term}")
    return term


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value


class SupplierEvidenceInput(BaseModel):
    field_path: str = Field(min_length=1, max_length=160)
    value: Any
    source_claim_id: str
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class SupplierCapabilityInput(BaseModel):
    product_concept_id: str
    source_claim_id: str
    specifications: dict[str, Any] = Field(default_factory=dict)
    certifications: list[str] = Field(default_factory=list)
    capacity: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class SupplierProfileCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    entity_id: str
    supplier_kind: SupplierKind
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[SupplierEvidenceInput] = Field(min_length=1)
    capabilities: list[SupplierCapabilityInput] = Field(default_factory=list)


class SupplierProfileView(OrmView):
    id: str
    entity_id: str
    supplier_kind: str
    review_status: str
    attributes_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class SupplierProfileBundle(BaseModel):
    profile: SupplierProfileView
    evidence: list[dict[str, Any]]
    capabilities: list[dict[str, Any]]


class SupplierCandidateCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    supplier_profile_id: str
    discovery_basis: list[dict[str, Any]] = Field(min_length=1)
    source_claim_ids: list[str] = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    displayed_price: dict[str, Any] | None = None


class SupplierCandidateView(OrmView):
    id: str
    route_id: str
    supplier_profile_id: str
    discovery_basis_json: list[dict[str, Any]]
    source_claim_ids_json: list[str]
    missing_fields_json: list[str]
    displayed_price_json: dict[str, Any] | None
    displayed_price_is_quote: bool
    whitelist_policy_ref: str | None
    whitelisted_by: str | None
    whitelisted_at: datetime | None
    status: str
    created_at: datetime


class CandidateWhitelistRequest(BaseModel):
    requested_by: str = Field(min_length=1, max_length=200)


class ProductRequirement(BaseModel):
    specification: dict[str, Any] = Field(default_factory=dict)
    packaging: dict[str, Any] | None = None
    certifications: list[str] | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=19, decimal_places=6)
    quantity_unit: str | None = Field(default=None, max_length=40)
    requested_delivery_at: datetime | None = None
    incoterm: str | None = None
    payment_terms: str | None = None

    @field_validator("requested_delivery_at")
    @classmethod
    def aware_delivery(cls, value: datetime | None):
        return None if value is None else _aware(value)

    @field_validator("incoterm")
    @classmethod
    def valid_incoterm(cls, value: str | None):
        return _incoterm(value)

    @model_validator(mode="after")
    def quantity_pair(self):
        if (self.quantity is None) != (self.quantity_unit is None):
            raise ValueError("quantity and quantity_unit must be supplied together")
        return self


class RfqCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    rfq_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    product_concept_id: str
    destination_country: str
    requirement: ProductRequirement
    extra_questions: list[str] = Field(default_factory=list)
    created_by: str = Field(min_length=1, max_length=200)

    @field_validator("destination_country")
    @classmethod
    def valid_country(cls, value: str):
        return _country(value)


class RfqFinalizeRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    expected_content_hash: str = Field(min_length=64, max_length=64)


class RfqVersionView(OrmView):
    id: str
    route_id: str
    rfq_key: str
    version_no: int
    product_concept_id: str
    requirement_json: dict[str, Any]
    quantity: Decimal | None
    quantity_unit: str | None
    destination_country: str
    incoterm: str | None
    requested_delivery_at: datetime | None
    questions_json: list[str]
    unresolved_fields_json: list[str]
    content_zh: str
    content_hash: str
    status: str
    created_by: str
    finalized_by: str | None
    finalized_at: datetime | None
    created_at: datetime


class AuthorizationContext(BaseModel):
    action_kind: Literal["supplier_whitelist", "supplier_rfq", "first_buyer_contact"]
    resource_id: str
    recipient_ref: str = Field(min_length=1, max_length=200)
    payload_hash: str = Field(min_length=64, max_length=64)
    supplier_whitelisted: bool = False
    eligibility_decision_id: str | None = None
    requested_by: str = Field(min_length=1, max_length=200)


class PolicyAuthorization(BaseModel):
    decision: Literal["allow", "deny", "require_approval"]
    policy_decision_ref: str
    policy_version: str
    approved_by: str | None = None
    expires_at: datetime | None = None
    reasons: list[str] = Field(default_factory=list)

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime | None):
        return None if value is None else _aware(value)


class SendTokenView(BaseModel):
    token: str
    token_id: str
    action_kind: str
    resource_id: str
    recipient_ref: str
    expires_at: datetime
    policy_decision_ref: str


class SendCommand(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    token: str = Field(min_length=20)
    actor: str = Field(min_length=1, max_length=200)


class RfqAuthorizationRequest(BaseModel):
    supplier_profile_id: str
    requested_by: str = Field(min_length=1, max_length=200)


class FirstContactAuthorizationRequest(BaseModel):
    requested_by: str = Field(min_length=1, max_length=200)


class OutboundMessageView(OrmView):
    id: str
    action_kind: str
    resource_id: str
    resource_version: int
    recipient_ref: str
    token_id: str
    gateway_name: str
    external_message_id: str
    receipt_json: dict[str, Any]
    payload_hash: str
    status: str
    sent_by: str
    sent_at: datetime


class SupplierQuoteIntake(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    supplier_profile_id: str
    rfq_version_id: str | None = None
    intake_format: Literal["email", "spreadsheet", "manual", "portal"]
    raw_artifact_ref: str = Field(min_length=1, max_length=500)
    raw_hash: str = Field(min_length=64, max_length=64)
    received_at: datetime
    currency: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    price_unit: str | None = Field(default=None, max_length=40)
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    moq_quantity: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=6)
    moq_unit: str | None = Field(default=None, max_length=40)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    tax: dict[str, Any] | None = None
    payment_terms: str | None = None
    incoterm: str | None = None
    valid_until: datetime | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    uncertain_fields: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str | None):
        return None if value is None else _currency(value)

    @field_validator("incoterm")
    @classmethod
    def valid_quote_incoterm(cls, value: str | None):
        return _incoterm(value)

    @field_validator("received_at")
    @classmethod
    def aware_received(cls, value: datetime):
        return _aware(value)

    @field_validator("valid_until")
    @classmethod
    def aware_valid_until(cls, value: datetime | None):
        return None if value is None else _aware(value)

    @model_validator(mode="after")
    def price_and_moq_pairs(self):
        if (self.unit_price is None) != (self.price_unit is None):
            raise ValueError("unit_price and price_unit must be supplied together")
        if (self.moq_quantity is None) != (self.moq_unit is None):
            raise ValueError("moq_quantity and moq_unit must be supplied together")
        return self


class QuoteParseResult(BaseModel):
    parser_version: str
    intake_format: Literal["email", "spreadsheet", "manual"]
    fields: dict[str, Any]
    uncertain_fields: list[str]


class SupplierQuoteView(OrmView):
    id: str
    route_id: str
    supplier_profile_id: str
    rfq_version_id: str | None
    intake_format: str
    raw_artifact_ref: str
    raw_hash: str
    currency: str | None
    unit_price: Decimal | None
    price_unit: str | None
    total_amount: Decimal | None
    moq_quantity: Decimal | None
    moq_unit: str | None
    lead_time_days: int | None
    tax_json: dict[str, Any] | None
    payment_terms: str | None
    incoterm: str | None
    valid_until: datetime | None
    specifications_json: dict[str, Any]
    uncertain_fields_json: list[str]
    review_status: str
    received_at: datetime
    created_at: datetime


class FxRateInput(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    source_ref: str = Field(min_length=1, max_length=300)
    as_of: datetime

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def valid_currency(cls, value: str):
        return _currency(value)

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime):
        return _aware(value)


class QuoteComparisonRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    quote_ids: list[str] = Field(min_length=2)
    target_currency: str
    target_unit: str = Field(min_length=1, max_length=40)
    target_incoterm: str
    fx_rates: list[FxRateInput] = Field(default_factory=list)
    incoterm_adjustments: dict[str, Decimal] = Field(default_factory=dict)
    unit_context: str | None = Field(default=None, max_length=80)

    @field_validator("target_currency")
    @classmethod
    def valid_target_currency(cls, value: str):
        return _currency(value)

    @field_validator("target_incoterm")
    @classmethod
    def valid_target_incoterm(cls, value: str):
        return _incoterm(value)


class QuoteComparisonView(OrmView):
    id: str
    route_id: str
    quote_ids_json: list[str]
    target_currency: str
    target_unit: str
    target_incoterm: str
    conversion_snapshot_json: dict[str, Any]
    rows_json: list[dict[str, Any]]
    specification_differences_json: dict[str, Any]
    assumptions_json: list[str]
    incomparable_quote_ids_json: list[str]
    created_at: datetime


class PerformanceEventCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    product_concept_id: str
    event_type: Literal["sample", "quality", "delivery", "claim"]
    predicted: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    outcome: Literal["success", "failure", "partial"] | None = None
    evidence_claim_id: str | None = None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred(cls, value: datetime):
        return _aware(value)


class PerformanceSnapshotRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    product_concept_id: str
    as_of: datetime
    minimum_history: int = Field(default=3, ge=1, le=100)

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime):
        return _aware(value)


class PerformanceSnapshotView(OrmView):
    id: str
    supplier_profile_id: str
    product_concept_id: str
    as_of: datetime
    event_count: int
    actual_event_count: int
    successful_actual_count: int
    score: float | None
    confidence_status: str
    metrics_json: dict[str, Any]
    created_at: datetime


class PerformanceEventView(OrmView):
    id: str
    supplier_profile_id: str
    product_concept_id: str
    event_type: str
    predicted_json: dict[str, Any] | None
    actual_json: dict[str, Any] | None
    outcome: str | None
    evidence_claim_id: str | None
    occurred_at: datetime
    created_at: datetime


class BuyerProfileCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    entity_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_claim_ids: list[str] = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class BuyerProfileView(OrmView):
    id: str
    entity_id: str
    attributes_json: dict[str, Any]
    evidence_claim_ids_json: list[str]
    review_status: str
    status: str
    created_at: datetime
    updated_at: datetime


class ContactPointInput(BaseModel):
    channel: Literal["email", "phone"]
    value: str = Field(min_length=3)
    source_claim_id: str
    lawful_basis: str = Field(min_length=2, max_length=60)
    jurisdiction: str
    captured_at: datetime

    @field_validator("jurisdiction")
    @classmethod
    def valid_jurisdiction(cls, value: str):
        return _country(value)

    @field_validator("captured_at")
    @classmethod
    def aware_captured(cls, value: datetime):
        return _aware(value)


class ContactAffiliationInput(BaseModel):
    buyer_profile_id: str
    role: str = Field(min_length=1, max_length=120)
    source_claim_id: str
    valid_from: datetime
    valid_to: datetime | None = None

    @field_validator("valid_from")
    @classmethod
    def aware_from(cls, value: datetime):
        return _aware(value)

    @field_validator("valid_to")
    @classmethod
    def aware_to(cls, value: datetime | None):
        return None if value is None else _aware(value)


class ContactCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    contact_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    display_name: str = Field(min_length=1, max_length=240)
    contact_points: list[ContactPointInput] = Field(min_length=1)
    affiliations: list[ContactAffiliationInput] = Field(min_length=1)


class ContactView(OrmView):
    id: str
    contact_key: str
    display_name: str
    status: str
    created_at: datetime
    updated_at: datetime


class ContactBundle(BaseModel):
    contact: ContactView
    contact_points: list[dict[str, Any]]
    affiliations: list[dict[str, Any]]


class SuppressionCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    channel: Literal["email", "phone", "all"]
    reason: Literal["unsubscribe", "complaint", "do_not_contact", "jurisdiction"]
    source_ref: str = Field(min_length=1, max_length=300)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred(cls, value: datetime):
        return _aware(value)


class EligibilityRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    channel: Literal["email", "phone"]
    jurisdiction: str
    purpose: Literal["first_contact", "reply", "transactional"]
    evaluated_at: datetime
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("jurisdiction")
    @classmethod
    def valid_jurisdiction(cls, value: str):
        return _country(value)

    @field_validator("evaluated_at")
    @classmethod
    def aware_evaluated(cls, value: datetime):
        return _aware(value)


class EligibilityDecisionView(OrmView):
    id: str
    contact_id: str
    channel: str
    jurisdiction: str
    decision: str
    blockers_json: list[str]
    policy_decision_ref: str | None
    policy_version: str | None
    evaluated_at: datetime
    created_at: datetime


class SuppressionView(OrmView):
    id: str
    contact_id: str
    channel: str
    reason: str
    source_ref: str
    active: bool
    occurred_at: datetime
    created_at: datetime


class GroundedContextItem(BaseModel):
    text: str = Field(min_length=1)
    claim_id: str


class MessageDraftCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    draft_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    buyer_profile_id: str
    contact_id: str
    eligibility_decision_id: str
    buyer_context: list[GroundedContextItem] = Field(min_length=1)
    capability_context: list[GroundedContextItem] = Field(min_length=1)
    desired_next_step: str = Field(min_length=1, max_length=500)
    proposed_subject: str | None = None
    proposed_body: str | None = None
    assertions: dict[str, str | None] = Field(default_factory=dict)
    created_by: str = Field(min_length=1, max_length=200)


class MessageDraftView(OrmView):
    id: str
    route_id: str
    buyer_profile_id: str
    contact_id: str
    eligibility_decision_id: str
    draft_key: str
    version_no: int
    subject: str
    body: str
    buyer_context_json: list[dict[str, Any]]
    capability_context_json: list[dict[str, Any]]
    context_claim_ids_json: list[str]
    required_confirmations_json: list[str]
    prohibited_findings_json: list[str]
    content_hash: str
    status: str
    created_by: str
    created_at: datetime


class InteractionIntake(BaseModel):
    external_message_id: str = Field(min_length=1, max_length=300)
    channel: Channel
    direction: Literal["inbound", "outbound"]
    raw_artifact_ref: str = Field(min_length=1, max_length=500)
    raw_hash: str = Field(min_length=64, max_length=64)
    body_text: str = Field(min_length=1)
    occurred_at: datetime
    thread_key: str | None = Field(default=None, max_length=300)
    explicit_route_id: str | None = None
    contact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachment_refs: list[str] = Field(default_factory=list)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred(cls, value: datetime):
        return _aware(value)


class InteractionView(OrmView):
    id: str
    external_message_id: str
    route_id: str | None
    contact_id: str | None
    thread_key: str | None
    channel: str
    direction: str
    raw_artifact_ref: str
    raw_hash: str
    body_text: str
    metadata_json: dict[str, Any]
    attachment_refs_json: list[str]
    link_method: str
    link_confidence: float
    status: str
    occurred_at: datetime
    created_at: datetime


class IntentClassifyRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    confidence_threshold: float = Field(default=0.75, ge=0.5, le=0.99)


class IntentAssessmentView(OrmView):
    id: str
    interaction_id: str
    classifier_version: str
    intent: str
    questions_json: list[str]
    objections_json: list[str]
    sentiment: str
    confidence: float
    needs_review: bool
    created_at: datetime


class QualificationField(BaseModel):
    value: Any
    source_interaction_id: str
    confidence: float = Field(ge=0, le=1)


class QualificationCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    as_of: datetime
    quantity: QualificationField | None = None
    specification: QualificationField | None = None
    budget: QualificationField | None = None
    timing: QualificationField | None = None
    authority: QualificationField | None = None
    procurement_process: QualificationField | None = None

    @field_validator("as_of")
    @classmethod
    def aware_as_of(cls, value: datetime):
        return _aware(value)


class QualificationSnapshotView(OrmView):
    id: str
    route_id: str
    as_of: datetime
    quantity_json: dict[str, Any] | None
    specification_json: dict[str, Any] | None
    budget_json: dict[str, Any] | None
    timing_json: dict[str, Any] | None
    authority_json: dict[str, Any] | None
    procurement_process_json: dict[str, Any] | None
    missing_fields_json: list[str]
    source_interaction_ids_json: list[str]
    created_at: datetime


class ConstraintAssessmentRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    qualification_snapshot_id: str
    quote_ids: list[str] = Field(min_length=1)


class ConstraintAssessmentView(OrmView):
    id: str
    route_id: str
    qualification_snapshot_id: str
    quote_ids_json: list[str]
    matrix_json: list[dict[str, Any]]
    conflicts_json: list[dict[str, Any]]
    candidate_solutions_json: list[dict[str, Any]]
    route_reassessment_required: bool
    created_at: datetime


class CostScenario(BaseModel):
    reference: str
    snapshot_hash: str = Field(min_length=64, max_length=64)
    calculator_version: str
    status: Literal["estimated", "confirmed"]
    total_cost: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    currency: str
    quantity: Decimal = Field(gt=0, max_digits=19, decimal_places=6)
    quantity_unit: str
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str):
        return _currency(value)


class BuyerQuoteBuildRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    quote_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    cost_scenario_ref: str = Field(min_length=1, max_length=200)
    margin_rate: Decimal = Field(ge=0, lt=1, max_digits=9, decimal_places=6)
    valid_until: datetime
    created_by: str = Field(min_length=1, max_length=200)

    @field_validator("valid_until")
    @classmethod
    def aware_valid_until(cls, value: datetime):
        return _aware(value)


class BuyerQuoteView(OrmView):
    id: str
    route_id: str
    quote_key: str
    version_no: int
    cost_scenario_ref: str
    cost_scenario_hash: str
    calculator_version: str
    cost_status: str
    cost_amount: Decimal
    margin_rate: Decimal
    selling_amount: Decimal
    currency: str
    quantity: Decimal
    quantity_unit: str
    valid_until: datetime
    assumptions_json: list[str]
    status: str
    approval_status: str
    created_by: str
    created_at: datetime


class NegotiationTermCreate(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    term_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    counterparty_ref: str = Field(min_length=1, max_length=200)
    terms: dict[str, Any]
    internal_floors: dict[str, Any]
    created_by: str = Field(min_length=1, max_length=200)


class NegotiationTermView(OrmView):
    id: str
    route_id: str
    term_key: str
    version_no: int
    terms_json: dict[str, Any]
    diff_json: dict[str, Any]
    floor_snapshot_hash: str
    floor_violations_json: list[dict[str, Any]]
    approval_required: bool
    counterparty_ref: str
    created_by: str
    created_at: datetime


class MeetingActionItem(BaseModel):
    task_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,159}$")
    owner: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=3)
    due_at: datetime

    @field_validator("due_at")
    @classmethod
    def aware_due(cls, value: datetime):
        return _aware(value)


class MeetingImport(BaseModel):
    external_ref: str = Field(min_length=1, max_length=300)
    raw_artifact_ref: str = Field(min_length=1, max_length=500)
    raw_hash: str = Field(min_length=64, max_length=64)
    summary: str = Field(min_length=1)
    occurred_at: datetime
    imported_by: str = Field(min_length=1, max_length=200)
    action_items: list[MeetingActionItem] = Field(default_factory=list)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred(cls, value: datetime):
        return _aware(value)


class MeetingImportResult(BaseModel):
    meeting_import_id: str
    interaction_id: str
    task_ids: list[str]
    duplicate: bool
