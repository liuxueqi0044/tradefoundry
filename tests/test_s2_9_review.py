from sqlalchemy import func, select

from tradefoundry.evidence.claims import ClaimExtractionService
from tradefoundry.evidence.contracts import ExtractionRequest, ReviewRequest
from tradefoundry.evidence.models import ClaimEvidenceRow, ClaimRow, ReviewDecisionRow
from tradefoundry.evidence.review import ClaimReviewService


def test_human_correction_preserves_model_claim_and_records_reason(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory()
    extraction_schema_factory(field_rules={"deadline": {"type": "date"}})
    original = ClaimExtractionService(session).extract(
        document.id,
        ExtractionRequest(
            schema_key="tender.claims",
            model_name="fixture-model",
            output={
                "claims": [
                    {
                        "subject_key": "tender:001",
                        "field_path": "deadline",
                        "value": "2026-10-01",
                        "evidence": ["html:1"],
                    }
                ]
            },
        ),
    )[0]
    corrected = ClaimReviewService(session).review(
        original.id,
        ReviewRequest(
            action="correct",
            reviewer="risk-officer@example.invalid",
            reason="Original page shows 15 October after corrigendum.",
            corrected_value="2026-10-15",
        ),
    )

    original_row = session.get(ClaimRow, original.id)
    decision = session.scalar(select(ReviewDecisionRow))
    assert original_row.value_json == "2026-10-01"
    assert original_row.status == "corrected"
    assert corrected.value_json == "2026-10-15"
    assert corrected.status == "verified"
    assert corrected.supersedes_claim_id == original.id
    assert decision.reviewer == "risk-officer@example.invalid"
    assert "corrigendum" in decision.reason
    assert session.scalar(select(func.count()).select_from(ClaimEvidenceRow)) == 2


def test_reviewer_can_verify_or_reject_with_append_only_decisions(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory(logical_id="review-actions")
    extraction_schema_factory(key="review.claims")
    output = {
        "claims": [
            {
                "subject_key": "review:1",
                "field_path": "buyer",
                "value": "Buyer A",
                "evidence": ["html:1"],
            },
            {
                "subject_key": "review:1",
                "field_path": "country",
                "value": "CN",
                "evidence": ["html:1"],
            },
        ]
    }
    claims = ClaimExtractionService(session).extract(
        document.id, ExtractionRequest(schema_key="review.claims", output=output)
    )
    service = ClaimReviewService(session)
    verified = service.review(
        claims[0].id,
        ReviewRequest(action="verify", reviewer="reviewer", reason="Confirmed against the page."),
    )
    rejected = service.review(
        claims[1].id,
        ReviewRequest(
            action="reject", reviewer="reviewer", reason="Country was inferred, not stated."
        ),
    )

    assert verified.status == "verified"
    assert rejected.status == "rejected"
    assert session.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 2
