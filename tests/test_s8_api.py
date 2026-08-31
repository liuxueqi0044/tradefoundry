from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session
from tradefoundry.ingestion.hashing import payload_hash

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _client(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_control_http_money_contract_records_fx_source(session):
    try:
        with _client(session) as client:
            quote = client.post(
                "/v1/control/fx-quotes",
                json={
                    "quote_key": "api-eur-usd",
                    "idempotency_key": "api-eur-usd",
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "rate": "1.10",
                    "source_name": "Official FX fixture",
                    "source_uri": "https://official.example.invalid/fx",
                    "quoted_at": (NOW - timedelta(hours=1)).isoformat(),
                    "valid_until": (NOW + timedelta(hours=1)).isoformat(),
                },
            )
            assert quote.status_code == 201, quote.text
            conversion = client.post(
                "/v1/control/money-conversions",
                json={
                    "idempotency_key": "api-conversion",
                    "money": {"amount": "100", "currency": "EUR"},
                    "target_currency": "USD",
                    "fx_quote_id": quote.json()["id"],
                    "converted_at": NOW.isoformat(),
                },
            )
            assert conversion.status_code == 201, conversion.text
            assert conversion.json()["target_amount"] == "110.0000"
            assert conversion.json()["source_snapshot_json"]["fx_source"] == ("Official FX fixture")
    finally:
        app.dependency_overrides.clear()


def test_control_http_policy_approval_and_token_pipeline(session):
    params = {
        "recipient_ref": "contact-api",
        "payload_hash": "a" * 64,
        "resource_version": 1,
        "actor": "operator-api",
    }
    try:
        with _client(session) as client:
            bundle = client.post(
                "/v1/control/policy-bundles",
                json={
                    "bundle_key": "api-actions",
                    "idempotency_key": "api-actions-bundle",
                    "backend": "local",
                    "rules": [
                        {
                            "rule_key": "first-contact-approval",
                            "priority": 10,
                            "actions": ["first_buyer_contact"],
                            "effect": "require_approval",
                            "conditions": [],
                            "reasons": ["First contact requires approval."],
                            "obligations": {
                                "approval_chain": [{"role": "compliance", "approvals": 1}],
                                "separation_of_duties": True,
                            },
                        }
                    ],
                    "created_by": "sol",
                },
            )
            assert bundle.status_code == 201, bundle.text
            activated = client.post(f"/v1/control/policy-bundles/{bundle.json()['id']}/activate")
            assert activated.json()["status"] == "active"
            decision = client.post(
                "/v1/control/policy-decisions",
                json={
                    "bundle_key": "api-actions",
                    "idempotency_key": "api-policy-decision",
                    "actor": "operator-api",
                    "actor_roles": ["sales"],
                    "action": "first_buyer_contact",
                    "resource_type": "message_draft",
                    "resource_id": "draft-api",
                    "context": {"params_hash": payload_hash(params)},
                },
            )
            assert decision.status_code == 201, decision.text
            assert decision.json()["decision"] == "require_approval"
            approval = client.post(
                "/v1/control/approval-requests",
                json={
                    "policy_decision_id": decision.json()["id"],
                    "idempotency_key": "api-approval",
                    "requester": "operator-api",
                    "params": params,
                    "subject_refs": ["entity:api-buyer"],
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            assert approval.status_code == 201, approval.text
            approved = client.post(
                f"/v1/control/approval-requests/{approval.json()['id']}/decisions",
                json={
                    "idempotency_key": "api-approval-decision",
                    "approver": "compliance-api",
                    "approver_roles": ["compliance"],
                    "decision": "approve",
                    "reason": "Compliance evidence and purpose were reviewed.",
                    "evidence_claim_ids": [],
                },
            )
            assert approved.json()["status"] == "approved"
            token = client.post(
                "/v1/control/execution-tokens",
                json={
                    "approval_request_id": approval.json()["id"],
                    "params": params,
                    "issued_by": "control-tower",
                    "ttl_seconds": 600,
                },
            )
            assert token.status_code == 201, token.text
            assert len(token.json()["token"]) >= 20
            assert token.json()["params_hash"] == payload_hash(params)
    finally:
        app.dependency_overrides.clear()


def test_openapi_exposes_all_board8_resource_families():
    paths = app.openapi()["paths"]
    expected = {
        "/v1/control/fx-quotes",
        "/v1/control/money-conversions",
        "/v1/control/cost-definitions",
        "/v1/control/landed-cost-scenarios",
        "/v1/control/cashflow-plans",
        "/v1/control/sensitivity-runs",
        "/v1/control/credit-assessments",
        "/v1/control/datasets/sync",
        "/v1/control/screenings",
        "/v1/control/export-control-assessments",
        "/v1/control/trade-requirement-assessments",
        "/v1/control/policy-bundles",
        "/v1/control/policy-decisions",
        "/v1/control/communication-decisions",
        "/v1/control/approval-requests",
        "/v1/control/execution-tokens",
        "/v1/control/risk-cases",
        "/v1/control/freezes",
        "/v1/control/audit-exports",
    }
    assert expected <= set(paths)
