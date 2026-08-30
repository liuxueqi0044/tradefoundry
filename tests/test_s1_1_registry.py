from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tradefoundry.ingestion.contracts import SourceCreate, SourceKind, SourceVersionCreate
from tradefoundry.ingestion.registry import SourceActivationError, SourceRegistry


def test_incomplete_source_cannot_be_activated_and_versions_are_immutable(session):
    registry = SourceRegistry(session)
    source = registry.create(
        SourceCreate(
            key="official-notices",
            name="Official notices",
            kind=SourceKind.OFFICIAL_API,
            owner="procurement-team",
            access_method="REST API",
        )
    )
    with pytest.raises(SourceActivationError) as error:
        registry.activate(source.id)
    assert "license_name" in error.value.missing
    assert "schedule_cron" in error.value.missing

    updated = registry.add_version(
        source.id,
        SourceVersionCreate(
            schedule_cron="0 */6 * * *",
            sla_hours=12,
            license_name="Open Government Licence",
            license_url="https://example.invalid/licence",
            terms_checked_at=datetime.now(UTC),
            commercial_use_allowed=True,
            retention_allowed=True,
            redistribution_allowed=False,
        ),
    )
    assert updated.current_version == 2
    assert updated.active is False
    active = registry.activate(source.id)
    assert active.active is True
    versions = registry.versions(source.id)
    assert [version.version_no for version in versions] == [1, 2]
    assert versions[0].license_name is None
    assert versions[1].license_name == "Open Government Licence"


def test_invalid_cron_is_rejected_at_activation(session):
    registry = SourceRegistry(session)
    source = registry.create(
        SourceCreate(
            key="invalid-cron",
            name="Invalid cron source",
            kind=SourceKind.MEMORY,
            owner="owner",
            access_method="fixture",
            schedule_cron="not a cron",
            sla_hours=1,
            license_name="Internal",
            license_url="https://example.invalid/license",
            terms_checked_at=datetime.now(UTC),
            commercial_use_allowed=True,
            retention_allowed=True,
        )
    )
    with pytest.raises(SourceActivationError) as error:
        registry.activate(source.id)
    assert "valid schedule_cron" in error.value.missing


def test_web_source_requires_auditable_permission_and_robots_decision(session):
    registry = SourceRegistry(session)
    source = registry.create(
        SourceCreate(
            key="governed-web",
            name="Governed public notices",
            kind=SourceKind.AUTHORIZED_WEB,
            owner="owner",
            access_method="authorized HTML",
            schedule_cron="0 0 * * *",
            sla_hours=24,
            license_name="Site terms",
            license_url="https://example.invalid/terms",
            terms_checked_at=datetime.now(UTC),
            commercial_use_allowed=True,
            retention_allowed=True,
            connector_config={"url": "https://example.invalid/notices"},
        )
    )
    with pytest.raises(SourceActivationError) as error:
        registry.activate(source.id)
    assert "connector_config.robots_checked_at" in error.value.missing
    assert "connector_config.permission_basis" in error.value.missing


def test_inline_connector_credentials_are_rejected_before_persistence():
    with pytest.raises(ValidationError, match="credential_ref"):
        SourceCreate(
            key="unsafe-secret",
            name="Unsafe secret source",
            kind=SourceKind.OFFICIAL_API,
            owner="owner",
            access_method="API",
            connector_config={"api_key": "must-not-be-stored"},
        )
