from __future__ import annotations

import base64
import binascii
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentStatus(StrEnum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"


class ClaimStatus(StrEnum):
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    VALIDATED = "validated"
    VERIFIED = "verified"
    REJECTED = "rejected"
    CORRECTED = "corrected"
    CONFLICT = "conflict"


class EvidenceIntakeRequest(BaseModel):
    logical_document_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=500)
    content_base64: str
    declared_media_type: str | None = Field(default=None, max_length=200)
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("content_base64 is not valid base64") from exc


class EvidenceDocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    logical_document_id: str
    version_no: int
    content_sha256: str
    artifact_sha256: str | None
    filename: str
    source_url: str | None
    declared_media_type: str | None
    detected_media_type: str
    size_bytes: int
    status: DocumentStatus
    security_status: str
    quarantine_reason: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class BoundingBox(BaseModel):
    left: float
    top: float
    right: float
    bottom: float
    coordinate_origin: str = "top_left"


class NormalizedBlock(BaseModel):
    key: str = Field(min_length=1, max_length=500)
    kind: str = Field(min_length=1, max_length=40)
    text: str
    page_no: int | None = Field(default=None, ge=1)
    bbox: dict[str, Any] | None = None
    section_path: list[str] = Field(default_factory=list)
    table_cell: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    schema_version: str = "1.0"
    converter_name: str
    converter_version: str
    status: str = "succeeded"
    page_count: int | None = Field(default=None, ge=0)
    markdown: str = ""
    blocks: list[NormalizedBlock] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ConversionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    converter_name: str
    converter_version: str
    schema_version: str
    status: str
    page_count: int | None
    table_count: int
    errors_json: list[dict[str, Any]]
    created_at: datetime


class EvidenceFragmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    conversion_id: str
    fragment_key: str
    fragment_type: str
    text: str
    page_no: int | None
    bbox_json: dict[str, Any] | None
    section_path: list[str]
    table_cell_json: dict[str, Any] | None
    content_hash: str
    metadata_json: dict[str, Any]
    created_at: datetime


class ExtractionSchemaCreate(BaseModel):
    schema_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")
    json_schema: dict[str, Any]
    field_rules: dict[str, dict[str, Any]] = Field(default_factory=dict)
    instructions: str = ""


class ExtractionSchemaView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_key: str
    version_no: int
    status: str
    json_schema: dict[str, Any]
    field_rules: dict[str, Any]
    instructions: str
    created_at: datetime


class ExtractionRequest(BaseModel):
    schema_key: str
    schema_version: int | None = Field(default=None, ge=1)
    method: str = Field(default="structured_output", min_length=2, max_length=80)
    model_name: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, max_length=100)
    output: dict[str, Any]


class ClaimCandidate(BaseModel):
    subject_key: str = Field(min_length=1, max_length=300)
    field_path: str = Field(min_length=1, max_length=300)
    value: Any
    evidence: list[str] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class ClaimView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    extraction_run_id: str | None
    schema_id: str
    subject_key: str
    field_path: str
    value_json: Any
    normalized_value_json: Any | None
    normalization_status: str
    unit: str | None
    currency: str | None
    confidence: float | None
    method: str
    method_version: str | None
    status: ClaimStatus
    valid_from: datetime | None
    valid_to: datetime | None
    observed_at: datetime
    supersedes_claim_id: str | None
    conflict_group_id: str | None
    created_at: datetime


class ReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(verify|reject|correct)$")
    reviewer: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)
    corrected_value: Any | None = None
    evidence: list[str] | None = None

    @field_validator("corrected_value")
    @classmethod
    def correction_may_be_falsey(cls, value: Any) -> Any:
        return value

    @model_validator(mode="after")
    def correction_fields(self):
        if self.action == "correct" and "corrected_value" not in self.model_fields_set:
            raise ValueError("corrected_value is required for correction")
        return self


class EvidenceLocation(BaseModel):
    fragment_id: str
    fragment_key: str
    fragment_type: str
    text: str
    page_no: int | None
    bbox: dict[str, Any] | None
    section_path: list[str]
    table_cell: dict[str, Any] | None


class EvidencePackage(BaseModel):
    claim_id: str
    supported: bool
    support_reason: str | None
    conclusion: Any
    normalized_conclusion: Any | None
    claim_status: str
    document_id: str
    logical_document_id: str
    document_version: int
    artifact_sha256: str
    artifact_uri: str
    locations: list[EvidenceLocation]
