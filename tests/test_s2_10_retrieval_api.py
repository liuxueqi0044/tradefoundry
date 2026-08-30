import base64

from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session
from tradefoundry.evidence.claims import ClaimExtractionService
from tradefoundry.evidence.contracts import ExtractionRequest, ReviewRequest
from tradefoundry.evidence.retrieval import EvidenceRetrievalService
from tradefoundry.evidence.review import ClaimReviewService


def test_evidence_package_returns_conclusion_location_hash_and_version(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory(logical_id="package-doc")
    extraction_schema_factory()
    claim = ClaimExtractionService(session).extract(
        document.id,
        ExtractionRequest(
            schema_key="tender.claims",
            output={
                "claims": [
                    {
                        "subject_key": "tender:package",
                        "field_path": "deadline",
                        "value": "2026-10-01",
                        "evidence": ["html:1"],
                    }
                ]
            },
        ),
    )[0]
    package = EvidenceRetrievalService(session).package(claim.id)

    assert package.supported is True
    assert package.document_version == 1
    assert package.artifact_sha256 == document.artifact_sha256
    assert package.locations[0].fragment_key == "html:1"
    assert package.locations[0].text == "Deadline 2026-10-01"


def test_evidence_http_flow(session, artifact_store, monkeypatch):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr("tradefoundry.api._artifact_store", lambda: artifact_store)
    client = TestClient(app)
    try:
        intake = client.post(
            "/v1/evidence/documents",
            json={
                "logical_document_id": "api-doc",
                "filename": "api.html",
                "declared_media_type": "text/html",
                "content_base64": base64.b64encode(
                    b"<html><h1>Notice</h1><p>Deadline 2026-10-01</p></html>"
                ).decode(),
            },
        )
        assert intake.status_code == 201
        document_id = intake.json()["id"]
        assert (
            client.post(
                f"/v1/evidence/documents/{document_id}/convert?converter=structured_text"
            ).status_code
            == 200
        )
        assert client.get(f"/v1/evidence/documents/{document_id}").status_code == 200
        fragments = client.get(f"/v1/evidence/documents/{document_id}/fragments")
        assert fragments.status_code == 200
        assert len(fragments.json()) == 2

        schema = client.post(
            "/v1/evidence/schemas",
            json={
                "schema_key": "api.claims",
                "json_schema": {
                    "type": "object",
                    "required": ["claims"],
                    "properties": {"claims": {"type": "array"}},
                },
            },
        ).json()
        assert (
            client.post(
                f"/v1/evidence/schemas/api.claims/versions/{schema['version_no']}/activate"
            ).status_code
            == 200
        )
        assert len(client.get("/v1/evidence/schemas/api.claims").json()) == 1
        claims = client.post(
            f"/v1/evidence/documents/{document_id}/extract",
            json={
                "schema_key": "api.claims",
                "output": {
                    "claims": [
                        {
                            "subject_key": "api:1",
                            "field_path": "deadline",
                            "value": "2026-10-01",
                            "evidence": ["html:1"],
                        }
                    ]
                },
            },
        )
        assert claims.status_code == 200
        claim_id = claims.json()[0]["id"]
        reviewed = client.post(
            f"/v1/evidence/claims/{claim_id}/review",
            json={
                "action": "verify",
                "reviewer": "api-reviewer",
                "reason": "Verified against the rendered fragment.",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "verified"
        package = client.get(f"/v1/evidence/claims/{claim_id}/package")
        assert package.status_code == 200
        assert package.json()["locations"][0]["fragment_key"] == "html:1"
        historical = client.get(
            "/v1/evidence/claims",
            params={"subject_key": "api:1", "as_of": "2027-01-01T00:00:00Z"},
        )
        assert historical.status_code == 200
        assert len(historical.json()) == 1
        assert (
            client.post(
                f"/v1/evidence/schemas/api.claims/versions/{schema['version_no']}/deprecate"
            ).status_code
            == 200
        )
        assert client.get("/v1/evidence/documents/missing").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_rejected_claim_is_returned_but_explicitly_unsupported(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory(logical_id="unsupported")
    extraction_schema_factory(key="unsupported.claims")
    claim = ClaimExtractionService(session).extract(
        document.id,
        ExtractionRequest(
            schema_key="unsupported.claims",
            output={
                "claims": [
                    {
                        "subject_key": "unsupported:1",
                        "field_path": "buyer",
                        "value": "Inferred Buyer",
                        "evidence": ["html:1"],
                    }
                ]
            },
        ),
    )[0]
    ClaimReviewService(session).review(
        claim.id,
        ReviewRequest(
            action="reject", reviewer="reviewer", reason="The source does not state this."
        ),
    )

    package = EvidenceRetrievalService(session).package(claim.id)
    assert package.supported is False
    assert package.support_reason == "claim_status_rejected"
