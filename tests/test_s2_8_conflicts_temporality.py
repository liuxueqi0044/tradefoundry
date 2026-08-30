from datetime import UTC, datetime

from tradefoundry.evidence.claims import ClaimExtractionService
from tradefoundry.evidence.contracts import ExtractionRequest
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.evidence.retrieval import EvidenceRetrievalService


def _request(value: str, valid_from: str, valid_to: str | None = None):
    claim = {
        "subject_key": "tender:temporal",
        "field_path": "deadline",
        "value": value,
        "evidence": ["html:1"],
        "valid_from": valid_from,
    }
    if valid_to:
        claim["valid_to"] = valid_to
    return ExtractionRequest(schema_key="tender.claims", output={"claims": [claim]})


def test_overlapping_different_claims_form_conflict_without_overwrite(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory()
    extraction_schema_factory(field_rules={"deadline": {"type": "date"}})
    service = ClaimExtractionService(session)
    first = service.extract(document.id, _request("2026-10-01", "2026-08-01T00:00:00Z"))[0]
    second = service.extract(document.id, _request("2026-10-15", "2026-08-15T00:00:00Z"))[0]

    first_row = session.get(ClaimRow, first.id)
    session.refresh(first_row)
    assert first_row.value_json == "2026-10-01"
    assert first_row.status == "conflict"
    assert second.status == "conflict"
    assert first_row.conflict_group_id == second.conflict_group_id


def test_as_of_returns_then_current_claim_not_later_version(
    session, evidence_document_factory, extraction_schema_factory
):
    document = evidence_document_factory(logical_id="temporality")
    extraction_schema_factory(field_rules={"deadline": {"type": "date"}})
    service = ClaimExtractionService(session)
    service.extract(
        document.id,
        _request("2026-10-01", "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"),
    )
    service.extract(document.id, _request("2026-10-15", "2026-08-20T00:00:00Z"))

    then = EvidenceRetrievalService(session).claims_as_of(
        "tender:temporal", datetime(2026, 8, 10, tzinfo=UTC)
    )
    current = EvidenceRetrievalService(session).claims_as_of(
        "tender:temporal", datetime(2026, 8, 30, tzinfo=UTC)
    )

    assert [claim.value_json for claim in then] == ["2026-10-01"]
    assert [claim.value_json for claim in current] == ["2026-10-15"]
