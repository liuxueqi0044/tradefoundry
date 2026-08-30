from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityType(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PROJECT = "project"
    PROCUREMENT = "procurement"
    AWARD = "award"
    PRODUCT = "product"
    LOCATION = "location"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    FROZEN = "frozen"


class AliasInput(BaseModel):
    value: str = Field(min_length=1, max_length=1000)
    language: str | None = Field(default=None, max_length=20)
    alias_type: str = Field(default="name", min_length=1, max_length=30)
    confidence: float = Field(default=1.0, ge=0, le=1)


class AttributeInput(BaseModel):
    field_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    value: Any
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_priority: int = Field(default=0, ge=-1000, le=1000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class EntityCreate(BaseModel):
    entity_key: str = Field(pattern=r"^[a-z0-9][a-z0-9:_.-]{2,199}$")
    entity_type: EntityType
    source_claim_id: str
    primary_name: str = Field(min_length=1, max_length=1000)
    language: str | None = Field(default=None, max_length=20)
    aliases: list[AliasInput] = Field(default_factory=list)
    attributes: list[AttributeInput] = Field(default_factory=list)
    risk_tier: str = Field(default="normal", pattern=r"^(normal|high|critical)$")


class EntityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_key: str
    entity_type: EntityType
    status: EntityStatus
    canonical_entity_id: str | None
    source_claim_id: str
    risk_tier: str
    frozen_reason: str | None
    created_at: datetime
    updated_at: datetime


class AliasView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    raw_value: str
    normalized_value: str
    tokens_json: list[str]
    language: str
    alias_type: str
    source_claim_id: str
    confidence: float


class IdentifierCreate(BaseModel):
    scheme: str = Field(pattern=r"^[a-z][a-z0-9:_-]{1,79}$")
    value: str = Field(min_length=1, max_length=1000)
    source_claim_id: str
    strength: str = Field(default="strong", pattern=r"^(strong|weak)$")


class IdentifierView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    scheme: str
    raw_value: str
    normalized_value: str
    strength: str
    status: str
    source_claim_id: str


class IdentifierResolutionResult(BaseModel):
    identifier: IdentifierView
    canonical_entity_id: str
    outcome: str
    merge_command_id: str | None = None
    conflict_id: str | None = None


class MergeRequest(BaseModel):
    winner_entity_id: str
    loser_entity_id: str
    idempotency_key: str = Field(min_length=3, max_length=200)
    decision_source: str = Field(default="human", max_length=50)
    actor: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)
    score: float | None = Field(default=None, ge=0, le=1)
    features: dict[str, Any] = Field(default_factory=dict)


class MergeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    winner_entity_id: str
    loser_entity_id: str
    decision_source: str
    score: float | None
    features_json: dict[str, Any]
    actor: str
    reason: str
    status: str
    created_at: datetime
    undone_at: datetime | None


class SplitRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    actor: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class UndoMergeRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class SplitView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    entity_id: str
    previous_canonical_entity_id: str
    actor: str
    reason: str
    created_at: datetime


class DistinctRequest(BaseModel):
    left_entity_id: str
    right_entity_id: str
    actor: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class GoldenField(BaseModel):
    value: Any
    raw_value: Any
    source_entity_id: str
    source_claim_id: str
    confidence: float
    source_priority: int
    selection_reason: str


class CanonicalProfile(BaseModel):
    canonical_entity: EntityView
    member_ids: list[str]
    aliases: list[AliasView]
    identifiers: list[IdentifierView]
    golden_fields: dict[str, GoldenField]


class MatchCandidateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    query_entity_id: str
    candidate_entity_id: str
    probability: float
    features_json: dict[str, Any]
    decision: str
    merge_command_id: str | None


class MatchReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(merge|reject)$")
    reviewer: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class IdentityConflictReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(merge|keep_distinct)$")
    reviewer: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class IdentityConflictView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scheme: str
    normalized_value: str
    left_entity_id: str
    right_entity_id: str
    reason: str
    status: str
    resolution_json: dict[str, Any] | None
    created_at: datetime


class MatchEvaluation(BaseModel):
    threshold: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float
    recall: float


class ProductConceptCreate(BaseModel):
    concept_key: str = Field(pattern=r"^[a-z0-9][a-z0-9:_.-]{2,159}$")
    preferred_label: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    source_claim_id: str
    parent_id: str | None = None


class ProductConceptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    concept_key: str
    entity_id: str
    preferred_label: str
    normalized_label: str
    parent_id: str | None
    status: str
    source_claim_id: str


class ProductSynonymCreate(BaseModel):
    label: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    source_claim_id: str


class ProductSynonymView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    concept_id: str
    label: str
    normalized_label: str
    language: str
    source_claim_id: str


class ProductSearchHit(BaseModel):
    concept: ProductConceptView
    score: float


class ProductCodeCreate(BaseModel):
    scheme: str = Field(pattern=r"^(hs|cpv|psc|unspsc|custom)$")
    code: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    method: str = Field(min_length=2, max_length=100)
    source_claim_id: str


class ProductCodeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    concept_id: str
    scheme: str
    code: str
    confidence: float
    status: str
    method: str
    source_claim_id: str
    reviewed_by: str | None
    review_reason: str | None


class ProductCodeReview(BaseModel):
    action: str = Field(pattern=r"^(verify|reject)$")
    reviewer: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)


class RequirementInput(BaseModel):
    requirement_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,119}$")
    mode: str = Field(pattern=r"^(required|optional|range|tolerance)$")
    value: Any
    unit: str | None = Field(default=None, max_length=80)
    target_unit: str | None = Field(default=None, max_length=80)
    original_text: str = Field(min_length=1, max_length=4000)
    source_claim_id: str | None = None


class SpecificationCreate(BaseModel):
    specification_key: str = Field(pattern=r"^[a-z0-9][a-z0-9:_.-]{2,199}$")
    concept_id: str
    version_no: int = Field(ge=1)
    original_text: str = Field(min_length=1)
    source_claim_id: str
    requirements: list[RequirementInput] = Field(min_length=1)


class RequirementView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    specification_id: str
    requirement_key: str
    mode: str
    value_json: Any
    normalized_value_json: Any
    unit: str | None
    original_text: str
    source_claim_id: str


class SpecificationView(BaseModel):
    id: str
    specification_key: str
    concept_id: str
    version_no: int
    original_text: str
    source_claim_id: str
    requirements: list[RequirementView]


class SpecificationDifference(BaseModel):
    requirement_key: str
    change_type: str
    left: RequirementView | None
    right: RequirementView | None


class RelationCreate(BaseModel):
    subject_entity_id: str
    relation_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    object_entity_id: str
    evidence_claim_id: str
    confidence: float = Field(ge=0, le=1)
    review_status: str = Field(default="candidate", pattern=r"^(candidate|verified)$")
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def valid_relation(self):
        if self.subject_entity_id == self.object_entity_id:
            raise ValueError("self-relations are not allowed")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class RelationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_entity_id: str
    relation_type: str
    object_entity_id: str
    evidence_claim_id: str
    confidence: float
    review_status: str
    valid_from: datetime | None
    valid_to: datetime | None


class RelationStep(BaseModel):
    relation: RelationView
    from_entity_id: str
    to_entity_id: str
    depth: int


class RelationPath(BaseModel):
    start_entity_id: str
    end_entity_id: str
    steps: list[RelationStep]


class EntitySearchHit(BaseModel):
    canonical_entity_id: str
    entity_type: str
    matched_alias: str
    normalized_alias: str
    score: float
    source_claim_id: str
