from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session


def test_tradealpha_feature_registry_http_contract(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            seeded = client.post("/v1/tradealpha/feature-definitions/seed")
            assert seeded.status_code == 200
            assert len(seeded.json()) == 8
            listed = client.get("/v1/tradealpha/feature-definitions")
            assert listed.status_code == 200
            assert {item["feature_key"] for item in listed.json()} >= {
                "event_reliability",
                "route_stage_progress",
                "evidence_completeness",
            }
            missing = client.get("/v1/tradealpha/scores/not-found/explanation")
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
