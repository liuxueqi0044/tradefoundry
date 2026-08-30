import pytest
from sqlalchemy import select

from tradefoundry.evidence.claims import ClaimExtractionService, ExtractionValidationError
from tradefoundry.evidence.contracts import ExtractionRequest
from tradefoundry.evidence.models import ExtractionRunRow


def test_structured_claim_is_schema_validated_and_requires_existing_evidence(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory()
    extraction_schema_factory(field_rules={"deadline": {"type": "date"}})
    request = ExtractionRequest(
        schema_key="tender.claims",
        model_name="fixture-model",
        prompt_version="p1",
        output={
            "claims": [
                {
                    "subject_key": "tender:001",
                    "field_path": "deadline",
                    "value": "2026-10-01",
                    "evidence": ["html:1"],
                    "confidence": 0.94,
                }
            ]
        },
    )
    claims = ClaimExtractionService(session).extract(document.id, request)

    assert len(claims) == 1
    assert claims[0].status == "validated"
    assert claims[0].normalized_value_json.startswith("2026-10-01T")


def test_invalid_or_ungrounded_output_is_blocked_and_audited(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory()
    extraction_schema_factory()
    request = ExtractionRequest(
        schema_key="tender.claims",
        output={
            "claims": [
                {
                    "subject_key": "tender:001",
                    "field_path": "deadline",
                    "value": "2026-10-01",
                    "evidence": ["invented-fragment"],
                }
            ]
        },
    )

    with pytest.raises(ExtractionValidationError):
        ClaimExtractionService(session).extract(document.id, request)

    run = session.scalar(select(ExtractionRunRow))
    assert run.status == "failed_validation"
    assert run.raw_output_json == request.output
    assert "unknown evidence" in run.errors_json[0]["message"]
