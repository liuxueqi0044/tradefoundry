from datetime import UTC, datetime

from bilateral_helpers import create_buyer_contact
from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session


def test_bilateral_http_contract_and_safe_defaults(
    session, deal_route_factory, master_entity_factory, master_claim_factory
):
    _, route = deal_route_factory()
    _, contact, _, _ = create_buyer_contact(session, master_entity_factory, master_claim_factory)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            missing = client.get("/v1/bilateral/suppliers/not-found")
            assert missing.status_code == 404

            eligibility = client.post(
                f"/v1/bilateral/contacts/{contact.id}/eligibility",
                json={
                    "idempotency_key": "api-eligibility-default-deny",
                    "channel": "email",
                    "jurisdiction": "KE",
                    "purpose": "first_contact",
                    "evaluated_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
                    "context": {},
                },
            )
            assert eligibility.status_code == 201
            assert eligibility.json()["decision"] == "deny"
            assert eligibility.json()["policy_decision_ref"] == "board8:not-connected"

            quote = client.post(
                f"/v1/bilateral/routes/{route.id}/buyer-quotes",
                json={
                    "idempotency_key": "api-buyer-quote-safe-default",
                    "quote_key": "api-buyer-quote",
                    "cost_scenario_ref": "cost:missing-board8",
                    "margin_rate": "0.2",
                    "valid_until": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
                    "created_by": "api-user",
                },
            )
            assert quote.status_code == 409
            assert "Board 8" in quote.json()["detail"]

            invalid_send = client.post(
                "/v1/bilateral/outbound/send",
                json={
                    "idempotency_key": "api-invalid-send",
                    "token": "invalid-token-that-is-long-enough",
                    "actor": "api-user",
                },
            )
            assert invalid_send.status_code == 409
            assert "invalid" in invalid_send.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_openapi_exposes_all_board7_resource_families():
    paths = app.openapi()["paths"]
    expected = {
        "/v1/bilateral/suppliers",
        "/v1/bilateral/routes/{route_id}/supplier-candidates",
        "/v1/bilateral/routes/{route_id}/rfqs",
        "/v1/bilateral/routes/{route_id}/supplier-quotes",
        "/v1/bilateral/routes/{route_id}/quote-comparisons",
        "/v1/bilateral/buyers",
        "/v1/bilateral/contacts/{contact_id}/eligibility",
        "/v1/bilateral/routes/{route_id}/message-drafts",
        "/v1/bilateral/interactions",
        "/v1/bilateral/routes/{route_id}/constraint-assessments",
        "/v1/bilateral/routes/{route_id}/buyer-quotes",
        "/v1/bilateral/routes/{route_id}/negotiation-terms",
        "/v1/bilateral/routes/{route_id}/meetings",
    }
    assert expected <= set(paths)
