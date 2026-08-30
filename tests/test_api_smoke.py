from datetime import UTC, datetime

from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session


def test_source_control_api_smoke(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}
            created = client.post(
                "/v1/sources",
                json={
                    "key": "api-fixture",
                    "name": "API fixture source",
                    "kind": "memory",
                    "owner": "api-test",
                    "access_method": "fixture",
                    "schedule_cron": "0 * * * *",
                    "sla_hours": 24,
                    "license_name": "Internal fixture",
                    "license_url": "https://example.invalid/license",
                    "terms_checked_at": datetime.now(UTC).isoformat(),
                    "commercial_use_allowed": True,
                    "retention_allowed": True,
                    "redistribution_allowed": False,
                    "connector_config": {"pages": [[{"id": "1"}]]},
                },
            )
            assert created.status_code == 201
            source = created.json()
            assert source["active"] is False
            activated = client.post(f"/v1/sources/{source['id']}/activate")
            assert activated.status_code == 200
            assert activated.json()["active"] is True
            assert len(client.get("/v1/sources").json()) == 1
    finally:
        app.dependency_overrides.clear()
