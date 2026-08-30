from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.contracts import (
    SourceCreate,
    SourceVersionCreate,
    SourceVersionView,
    SourceView,
)
from tradefoundry.ingestion.models import SourceRow, SourceVersionRow


class SourceNotFoundError(LookupError):
    pass


class SourceActivationError(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("source cannot be activated: " + ", ".join(missing))


class SourceRegistry:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: SourceCreate) -> SourceView:
        source = SourceRow(
            id=str(uuid4()),
            key=request.key,
            kind=request.kind.value,
            active=False,
            current_version=1,
        )
        version = SourceVersionRow(
            id=str(uuid4()),
            source_id=source.id,
            version_no=1,
            **self._create_values(request),
        )
        self.session.add_all([source, version])
        self.session.commit()
        return self._view(source, version)

    def add_version(self, source_id: str, request: SourceVersionCreate) -> SourceView:
        source, current = self._rows(source_id)
        values = self._version_values(current)
        changes = request.model_dump(exclude_unset=True, mode="python")
        self._normalize_urls(changes)
        values.update(changes)
        version_no = source.current_version + 1
        version = SourceVersionRow(
            id=str(uuid4()), source_id=source.id, version_no=version_no, **values
        )
        source.current_version = version_no
        source.active = False
        source.updated_at = datetime.now(UTC)
        self.session.add(version)
        self.session.commit()
        return self._view(source, version)

    def activate(self, source_id: str) -> SourceView:
        source, version = self._rows(source_id)
        missing = self.activation_errors(version, source.kind)
        if missing:
            raise SourceActivationError(missing)
        source.active = True
        source.updated_at = datetime.now(UTC)
        self.session.commit()
        return self._view(source, version)

    def deactivate(self, source_id: str) -> SourceView:
        source, version = self._rows(source_id)
        source.active = False
        source.updated_at = datetime.now(UTC)
        self.session.commit()
        return self._view(source, version)

    def get(self, source_id: str) -> SourceView:
        source, version = self._rows(source_id)
        return self._view(source, version)

    def get_by_key(self, key: str) -> SourceView:
        source = self.session.scalar(select(SourceRow).where(SourceRow.key == key))
        if source is None:
            raise SourceNotFoundError(key)
        return self.get(source.id)

    def list(self) -> list[SourceView]:
        sources = self.session.scalars(select(SourceRow).order_by(SourceRow.key)).all()
        return [self.get(source.id) for source in sources]

    def versions(self, source_id: str) -> list[SourceVersionView]:
        self._source(source_id)
        rows = self.session.scalars(
            select(SourceVersionRow)
            .where(SourceVersionRow.source_id == source_id)
            .order_by(SourceVersionRow.version_no)
        ).all()
        return [SourceVersionView.model_validate(row) for row in rows]

    @staticmethod
    def activation_errors(version: SourceVersionRow, source_kind: str | None = None) -> list[str]:
        required = {
            "owner": version.owner,
            "access_method": version.access_method,
            "schedule_cron": version.schedule_cron,
            "sla_hours": version.sla_hours,
            "license_name": version.license_name,
            "license_url": version.license_url,
            "terms_checked_at": version.terms_checked_at,
        }
        errors = [name for name, value in required.items() if value in (None, "")]
        if version.commercial_use_allowed is not True:
            errors.append("commercial_use_allowed=true")
        if version.retention_allowed is not True:
            errors.append("retention_allowed=true")
        if version.schedule_cron:
            try:
                croniter(version.schedule_cron)
            except (KeyError, ValueError):
                errors.append("valid schedule_cron")
        if source_kind == "authorized_web":
            web_requirements = {
                "connector_config.policy_decision=allow": version.connector_config.get(
                    "policy_decision"
                )
                == "allow",
                "connector_config.robots_allowed=true": version.connector_config.get(
                    "robots_allowed"
                )
                is True,
                "connector_config.robots_checked_at": version.connector_config.get(
                    "robots_checked_at"
                ),
                "connector_config.permission_basis": version.connector_config.get(
                    "permission_basis"
                ),
            }
            errors.extend(name for name, value in web_requirements.items() if not value)
        return errors

    def _rows(self, source_id: str) -> tuple[SourceRow, SourceVersionRow]:
        source = self._source(source_id)
        version = self.session.scalar(
            select(SourceVersionRow).where(
                SourceVersionRow.source_id == source.id,
                SourceVersionRow.version_no == source.current_version,
            )
        )
        if version is None:
            raise RuntimeError(f"source {source_id} has no current version")
        return source, version

    def _source(self, source_id: str) -> SourceRow:
        source = self.session.get(SourceRow, source_id)
        if source is None:
            raise SourceNotFoundError(source_id)
        return source

    @staticmethod
    def _create_values(request: SourceCreate) -> dict:
        values = request.model_dump(exclude={"key", "kind"}, mode="python")
        SourceRegistry._normalize_urls(values)
        return values

    @staticmethod
    def _normalize_urls(values: dict) -> None:
        for field in ("access_url", "license_url"):
            if values.get(field) is not None:
                values[field] = str(values[field])

    @staticmethod
    def _version_values(version: SourceVersionRow) -> dict:
        return {
            "name": version.name,
            "owner": version.owner,
            "access_url": version.access_url,
            "access_method": version.access_method,
            "schedule_cron": version.schedule_cron,
            "sla_hours": version.sla_hours,
            "license_name": version.license_name,
            "license_url": version.license_url,
            "terms_checked_at": version.terms_checked_at,
            "commercial_use_allowed": version.commercial_use_allowed,
            "retention_allowed": version.retention_allowed,
            "redistribution_allowed": version.redistribution_allowed,
            "connector_config": version.connector_config,
            "quality_config": version.quality_config,
        }

    @staticmethod
    def _view(source: SourceRow, version: SourceVersionRow) -> SourceView:
        return SourceView(
            id=source.id,
            key=source.key,
            kind=source.kind,
            active=source.active,
            current_version=source.current_version,
            created_at=source.created_at,
            updated_at=source.updated_at,
            version=SourceVersionView.model_validate(version),
        )
