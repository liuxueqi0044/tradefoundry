from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

INLINE_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "password",
    "secret",
    "token",
}


def reject_inline_secrets(value: Any, path: str = "connector_config") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in INLINE_SECRET_KEYS:
                raise ValueError(
                    f"{path}.{key} contains an inline credential; use credential_ref instead"
                )
            reject_inline_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_inline_secrets(item, f"{path}[{index}]")


class SourceKind(StrEnum):
    OFFICIAL_API = "official_api"
    BULK_FILE = "bulk_file"
    OCDS = "ocds"
    AUTHORIZED_WEB = "authorized_web"
    MEMORY = "memory"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChangeType(StrEnum):
    ADDED = "added"
    UPDATED = "updated"
    REVOKED = "revoked"
    DEADLINE_CHANGED = "deadline_changed"
    ATTACHMENT_CHANGED = "attachment_changed"


class SourceCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    name: str = Field(min_length=3, max_length=200)
    kind: SourceKind
    owner: str = Field(min_length=2, max_length=200)
    access_url: HttpUrl | None = None
    access_method: str = Field(min_length=2, max_length=100)
    schedule_cron: str | None = None
    sla_hours: int | None = Field(default=None, gt=0, le=8760)
    license_name: str | None = None
    license_url: HttpUrl | None = None
    terms_checked_at: datetime | None = None
    commercial_use_allowed: bool | None = None
    retention_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    connector_config: dict[str, Any] = Field(default_factory=dict)
    quality_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def prohibit_inline_credentials(self):
        reject_inline_secrets(self.connector_config)
        return self


class SourceVersionCreate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    owner: str | None = Field(default=None, min_length=2, max_length=200)
    access_url: HttpUrl | None = None
    access_method: str | None = Field(default=None, min_length=2, max_length=100)
    schedule_cron: str | None = None
    sla_hours: int | None = Field(default=None, gt=0, le=8760)
    license_name: str | None = None
    license_url: HttpUrl | None = None
    terms_checked_at: datetime | None = None
    commercial_use_allowed: bool | None = None
    retention_allowed: bool | None = None
    redistribution_allowed: bool | None = None
    connector_config: dict[str, Any] | None = None
    quality_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        if self.connector_config is not None:
            reject_inline_secrets(self.connector_config)
        return self


class SourceVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    name: str
    owner: str
    access_url: str | None
    access_method: str
    schedule_cron: str | None
    sla_hours: int | None
    license_name: str | None
    license_url: str | None
    terms_checked_at: datetime | None
    commercial_use_allowed: bool | None
    retention_allowed: bool | None
    redistribution_allowed: bool | None
    connector_config: dict[str, Any]
    quality_config: dict[str, Any]
    created_at: datetime


class SourceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    kind: SourceKind
    active: bool
    current_version: int
    created_at: datetime
    updated_at: datetime
    version: SourceVersionView


class TimeWindow(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self


class ArtifactCandidate(BaseModel):
    content: bytes
    media_type: str
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawArtifactRef(BaseModel):
    sha256: str
    uri: str
    size_bytes: int
    media_type: str


class SourceRecordCandidate(BaseModel):
    external_id: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    effective_at: datetime | None = None
    revoked: bool = False
    deadline: datetime | None = None
    attachment_hashes: list[str] = Field(default_factory=list)
    artifact_index: int | None = Field(default=None, ge=0)
    relation: dict[str, Any] = Field(default_factory=dict)


class ConnectorBatch(BaseModel):
    artifacts: list[ArtifactCandidate] = Field(default_factory=list)
    records: list[SourceRecordCandidate] = Field(default_factory=list)
    next_cursor: dict[str, Any] | None = None
    metrics: dict[str, int | float | str] = Field(default_factory=dict)
    quarantined: list[QuarantineCandidate] = Field(default_factory=list)


class QuarantineCandidate(BaseModel):
    reason_code: str
    message: str
    payload: dict[str, Any] | list[Any] | str | None = None


class ConnectorContext(BaseModel):
    source_id: str
    source_key: str
    source_version: int
    connector_version: str
    config: dict[str, Any]
    cursor: dict[str, Any] | None = None
    window: TimeWindow


class FetchRunCreate(BaseModel):
    source_id: str
    window: TimeWindow
    cursor: dict[str, Any] | None = None
    priority: int = Field(default=100, ge=0, le=1000)


class FetchRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    status: RunStatus
    window_start: datetime
    window_end: datetime
    attempt: int
    priority: int
    cursor_before: dict[str, Any] | None
    cursor_after: dict[str, Any] | None
    metrics: dict[str, Any]
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    parent_run_id: str | None


class QualityThresholds(BaseModel):
    minimum_records: int = Field(default=1, ge=0)
    maximum_drop_ratio: float = Field(default=0.7, ge=0, le=1)
    maximum_duplicate_ratio: float = Field(default=0.2, ge=0, le=1)
    maximum_field_drop_ratio: float = Field(default=0.7, ge=0, le=1)
    maximum_time_drift_hours: float = Field(default=72, ge=0)
    maximum_consecutive_failures: int = Field(default=3, ge=1)


class QualityResult(BaseModel):
    score: int = Field(ge=0, le=100)
    status: str
    anomalies: list[str]
    metrics: dict[str, Any]


class ReplayRequest(BaseModel):
    source_id: str
    window: TimeWindow
    connector_version: str | None = None


class ReplayReport(BaseModel):
    id: str
    source_id: str
    original_run_id: str | None
    replay_run_id: str
    added_hashes: list[str]
    missing_hashes: list[str]
    unchanged_hashes: list[str]
    created_at: datetime
