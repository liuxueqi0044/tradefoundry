from datetime import UTC, datetime

from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session
from tradefoundry.opportunity.auditor import HypothesisAuditor
from tradefoundry.opportunity.compiler import OpportunityCompiler
from tradefoundry.opportunity.contracts import (
    AuditRequest,
    CompileRequest,
    IssuanceRequest,
)
from tradefoundry.opportunity.issuance import DealCellIssuanceService


def test_issuance_gateway_denies_unapproved_and_emits_one_versioned_command_after_pass(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    product = product_concept_factory()
    event = world_event_factory(product_concept_id=product.id)
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["rfq"],
        signal_types=["explicit_rfq"],
    )
    hypothesis = OpportunityCompiler(session).compile(
        CompileRequest(
            event_id=event.id,
            template_id=template.id,
            correlation_id="issuance-compile",
        )
    )[0]
    service = DealCellIssuanceService(session)
    denied = service.issue(
        hypothesis.id,
        IssuanceRequest(
            idempotency_key="issue:denied",
            requested_by="operator",
            correlation_id="issue-denied",
        ),
    )
    assert denied.command_status == "denied"
    assert denied.rejection_reason

    HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="issue:audit-pass",
            actor="sol-auditor",
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )
    request = IssuanceRequest(
        idempotency_key="issue:ready",
        requested_by="operator",
        correlation_id="issue-ready",
    )
    ready = service.issue(hypothesis.id, request)
    repeated = service.issue(hypothesis.id, request)

    assert ready.command_status == "ready"
    assert repeated.id == ready.id
    assert ready.payload_json["contract_version"] == "deal-cell-create-command-v1"
    assert ready.payload_json["template"]["version"] == 1
    assert ready.payload_json["audit"]["auditor_version"]
    assert "budget" not in ready.payload_json


def test_opportunity_http_contract_exposes_compilation_audit_and_issuance(
    session,
    master_claim_factory,
    master_entity_factory,
    product_concept_factory,
):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        product = product_concept_factory()
        buyer = master_entity_factory(name="API Buyer")
        claim = master_claim_factory(
            value="RFQ for industrial valves",
            field_path="procurement.notice",
            verified=True,
        )
        event_response = client.post(
            "/v1/opportunities/events",
            json={
                "title": "Industrial valve RFQ",
                "event_type": "rfq",
                "occurred_at": "2026-08-30T00:00:00Z",
                "expires_at": "2026-10-30T00:00:00Z",
                "country_code": "KE",
                "reliability": 0.95,
                "evidence_claim_ids": [claim.id],
                "subjects": [{"entity_id": buyer.id, "role": "buyer", "claim_id": claim.id}],
                "products": [
                    {
                        "product_concept_id": product.id,
                        "claim_id": claim.id,
                        "certainty": 0.93,
                    }
                ],
                "correlation_id": "http-opportunity",
            },
        )
        assert event_response.status_code == 201
        event_id = event_response.json()["id"]
        assert client.get(f"/v1/opportunities/events/{event_id}").status_code == 200
        signals = client.post(f"/v1/opportunities/events/{event_id}/classify")
        assert signals.status_code == 200
        assert signals.json()[0]["signal_type"] == "explicit_rfq"
        template_response = client.post(
            "/v1/opportunities/templates",
            json={
                "template_key": "api-rfq-template",
                "idempotency_key": "api-template-create",
                "name": "API RFQ Template",
                "event_types": ["rfq"],
                "signal_types": ["explicit_rfq"],
                "product_concept_ids": [product.id],
                "created_by": "api-owner",
            },
        )
        assert template_response.status_code == 201
        template_id = template_response.json()["id"]
        assert client.get(f"/v1/opportunities/templates/{template_id}").status_code == 200
        assert (
            client.post(
                f"/v1/opportunities/templates/{template_id}/activate",
                json={"actor": "api-owner", "reason": "Acceptance activation."},
            ).status_code
            == 200
        )
        applicable = client.get(f"/v1/opportunities/events/{event_id}/templates")
        assert applicable.json()[0]["id"] == template_id
        needs = client.post(f"/v1/opportunities/events/{event_id}/templates/{template_id}/needs")
        assert needs.status_code == 200
        assert needs.json()[0]["basis_type"] == "explicit_claim"
        assert client.post(f"/v1/opportunities/events/{event_id}/participants").status_code == 200
        routes = client.post(f"/v1/opportunities/events/{event_id}/routes")
        assert len(routes.json()) == 4
        compile_response = client.post(
            "/v1/opportunities/hypotheses/compile",
            json={
                "event_id": event_id,
                "template_id": template_id,
                "correlation_id": "http-compile",
            },
        )
        assert compile_response.status_code == 201
        hypothesis_id = compile_response.json()[0]["id"]
        assert client.get(f"/v1/opportunities/hypotheses/{hypothesis_id}").status_code == 200
        audit_response = client.post(
            f"/v1/opportunities/hypotheses/{hypothesis_id}/audit",
            json={
                "idempotency_key": "http-audit",
                "actor": "sol-auditor",
                "as_of": "2026-09-01T00:00:00Z",
            },
        )
        assert audit_response.json()["decision"] == "pass"
        issue_response = client.post(
            f"/v1/opportunities/hypotheses/{hypothesis_id}/issue",
            json={
                "idempotency_key": "http-issue",
                "requested_by": "api-operator",
                "correlation_id": "http-issue",
            },
        )
        assert issue_response.status_code == 200
        assert issue_response.json()["command_status"] == "ready"
        deprecated = client.post(
            f"/v1/opportunities/templates/{template_id}/deprecate",
            json={"actor": "api-owner", "reason": "End acceptance lifecycle."},
        )
        assert deprecated.json()["status"] == "deprecated"
        assert client.get("/v1/opportunities/events/missing").status_code == 404
    finally:
        app.dependency_overrides.clear()
