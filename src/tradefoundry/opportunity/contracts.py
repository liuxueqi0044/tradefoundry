from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventType(StrEnum):
    RFQ = "rfq"
    PROJECT_APPROVAL = "project_approval"
    AWARD = "award"
    EXPANSION = "expansion"
    REGULATORY_CHANGE = "regulatory_change"
    SUPPLY_DISRUPTION = "supply_disruption"
    OTHER = "other"


class SignalType(StrEnum):
    EXPLICIT_RFQ = "explicit_rfq"
    PROJECT_APPROVAL = "project_approval"
    AWARD = "award"
    EXPANSION = "expansion"
    REGULATORY_CHANGE = "regulatory_change"
    SUPPLY_DISRUPTION = "supply_disruption"
    OTHER = "other"


class ParticipantRole(StrEnum):
    BUYER = "buyer"
    EPC = "epc"
    DISTRIBUTOR = "distributor"
    SUPPLIER = "supplier"
    AWARDEE = "awardee"
    INFLUENCER = "influencer"


class RouteType(StrEnum):
    DIRECT_BID = "direct_bid"
    PRE_AWARD_SUPPLY = "pre_award_supply"
    POST_AWARD_SUPPLY = "post_award_supply"
    CHANNEL = "channel"


class EventSubjectInput(BaseModel):
    entity_id: str
    role: str = Field(min_length=1, max_length=60)
    claim_id: str


class EventProductInput(BaseModel):
    product_concept_id: str
    claim_id: str
    certainty: float = Field(ge=0, le=1)


class WorldEventCreate(BaseModel):
    title: str = Field(min_length=3, max_length=1000)
    event_type: EventType
    occurred_at: datetime
    expires_at: datetime | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    location_entity_id: str | None = None
    reliability: float = Field(ge=0, le=1)
    evidence_claim_ids: list[str] = Field(min_length=1)
    subjects: list[EventSubjectInput] = Field(min_length=1)
    products: list[EventProductInput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=100)

    @field_validator("country_code")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_times_and_evidence(self):
        if self.expires_at is not None and self.expires_at <= self.occurred_at:
            raise ValueError("expires_at must be after occurred_at")
        referenced = set(self.evidence_claim_ids)
        referenced.update(subject.claim_id for subject in self.subjects)
        referenced.update(product.claim_id for product in self.products)
        self.evidence_claim_ids = sorted(referenced)
        return self


class WorldEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fingerprint: str
    title: str
    event_type: str
    occurred_at: datetime
    expires_at: datetime | None
    country_code: str | None
    location_entity_id: str | None
    reliability: float
    status: str
    facts_snapshot_json: dict[str, Any]
    metadata_json: dict[str, Any]
    correlation_id: str
    created_at: datetime


class SignalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    signal_type: str
    priority: int
    confidence: float
    basis_json: dict[str, Any]
    classifier_version: str
    created_at: datetime


class ForbiddenCondition(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    operator: Literal["equals", "contains", "in"]
    value: Any
    reason: str = Field(min_length=3)


class ProductNeedRule(BaseModel):
    product_concept_id: str
    basis: str = Field(min_length=3)
    confidence: float = Field(gt=0, lt=1)
    uncertainty: str = Field(min_length=3)
    applicable_event_types: list[EventType] = Field(default_factory=list)
    applicable_signal_types: list[SignalType] = Field(default_factory=list)
    required_claim_fields: list[str] = Field(default_factory=list)


class TemplateCreate(BaseModel):
    template_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,99}$")
    idempotency_key: str = Field(min_length=3, max_length=200)
    name: str = Field(min_length=3, max_length=300)
    description: str = ""
    event_types: list[EventType] = Field(min_length=1)
    signal_types: list[SignalType] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    product_concept_ids: list[str] = Field(default_factory=list)
    required_claim_fields: list[str] = Field(default_factory=list)
    forbidden_conditions: list[ForbiddenCondition] = Field(default_factory=list)
    product_need_rules: list[ProductNeedRule] = Field(default_factory=list)
    created_by: str = Field(min_length=1, max_length=200)

    @field_validator("country_codes")
    @classmethod
    def normalize_countries(cls, value: list[str]) -> list[str]:
        normalized = sorted({country.upper() for country in value})
        if any(len(country) != 2 for country in normalized):
            raise ValueError("country codes must be ISO alpha-2 values")
        return normalized


class TemplateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_key: str
    version_no: int
    idempotency_key: str
    name: str
    description: str
    status: str
    event_types_json: list[str]
    signal_types_json: list[str]
    country_codes_json: list[str]
    product_concept_ids_json: list[str]
    required_claim_fields_json: list[str]
    forbidden_conditions_json: list[dict[str, Any]]
    product_need_rules_json: list[dict[str, Any]]
    created_by: str
    created_at: datetime


class TemplateStateRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3)


class ProductNeedView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    event_id: str
    template_id: str
    product_concept_id: str
    basis_type: str
    confidence: float
    uncertainty: str
    derivation_chain_json: list[dict[str, Any]]
    supporting_claim_ids_json: list[str]
    derivation_version: str
    created_at: datetime


class LLMProductNeedProposal(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    product_concept_id: str
    confidence: float = Field(gt=0, le=0.85)
    uncertainty: str = Field(min_length=3)
    reasoning_summary: str = Field(min_length=3, max_length=2000)
    supporting_claim_ids: list[str] = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)


class ParticipantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    entity_id: str
    role: str
    confidence: float
    hop_distance: int
    basis_json: dict[str, Any]
    evidence_claim_ids_json: list[str]
    discovery_version: str
    created_at: datetime


class RouteView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    route_type: str
    feasibility: str
    participant_candidate_ids_json: list[str]
    reasons_json: list[str]
    missing_requirements_json: list[str]
    generator_version: str
    input_hash: str
    created_at: datetime


class NumericAssertion(BaseModel):
    label: str = Field(min_length=1)
    value: int | float
    claim_id: str | None = None


class CompileRequest(BaseModel):
    event_id: str
    template_id: str
    correlation_id: str = Field(min_length=1, max_length=100)
    counter_evidence: list[dict[str, Any]] = Field(default_factory=list)
    additional_unknowns: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    numeric_assertions: list[NumericAssertion] = Field(default_factory=list)


class HypothesisView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fingerprint: str
    statement: str
    event_ids_json: list[str]
    template_id: str
    product_need_ids_json: list[str]
    buyer_candidate_ids_json: list[str]
    supplier_candidate_ids_json: list[str]
    route_candidate_ids_json: list[str]
    fact_assertions_json: list[dict[str, Any]]
    inference_assertions_json: list[dict[str, Any]]
    supporting_claim_ids_json: list[str]
    counter_evidence_json: list[dict[str, Any]]
    unknowns_json: list[str]
    risks_json: list[str]
    probability_low: float
    probability_high: float
    probe_actions_json: list[dict[str, Any]]
    stop_conditions_json: list[str]
    numeric_assertions_json: list[dict[str, Any]]
    compiler_version: str
    audit_status: str
    correlation_id: str
    created_at: datetime


class AuditRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    actor: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(default="opportunity-policy-v1", min_length=1)
    policy_flags: list[str] = Field(default_factory=list)
    as_of: datetime | None = None


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    hypothesis_id: str
    decision: str
    reasons_json: list[str]
    checks_json: dict[str, Any]
    policy_version: str
    auditor_version: str
    actor: str
    created_at: datetime


class IssuanceRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    requested_by: str = Field(min_length=1, max_length=200)
    correlation_id: str = Field(min_length=1, max_length=100)


class IssuanceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    hypothesis_id: str
    command_status: str
    deal_cell_key: str | None
    payload_json: dict[str, Any]
    rejection_reason: str | None
    requested_by: str
    correlation_id: str
    created_at: datetime


class CompilerRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    input_hash: str
    compiler_version: str
    correlation_id: str
    status: str
    duration_ms: int
    metrics_json: dict[str, Any]
    error_type: str | None
    created_at: datetime
