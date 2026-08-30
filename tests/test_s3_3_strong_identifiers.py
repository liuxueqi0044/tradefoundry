import pytest

from tradefoundry.master.contracts import (
    DistinctRequest,
    IdentifierCreate,
    IdentityConflictReviewRequest,
)
from tradefoundry.master.identifiers import IdentifierResolutionService
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import EntityRow, IdentityConflictRow
from tradefoundry.master.resolution import ResolutionService


def test_exact_strong_identifier_merges_entities_deterministically(
    session, master_entity_factory, master_claim_factory
):
    first = master_entity_factory(name="Acme Ltd")
    second = master_entity_factory(name="ACME Trading")
    service = IdentifierResolutionService(session)
    service.add(
        first.id,
        IdentifierCreate(
            scheme="domain", value="www.acme.example", source_claim_id=master_claim_factory().id
        ),
    )
    result = service.add(
        second.id,
        IdentifierCreate(
            scheme="domain", value="https://acme.example", source_claim_id=master_claim_factory().id
        ),
    )

    assert result.outcome == "auto_merged"
    assert result.merge_command_id is not None
    assert canonical_root(session, first.id).id == canonical_root(session, second.id).id


def test_strong_identifier_contradicting_distinct_constraint_freezes_both(
    session, master_entity_factory, master_claim_factory
):
    first = master_entity_factory(name="ABC Holdings")
    second = master_entity_factory(name="ABC Hospital")
    ResolutionService(session).mark_distinct(
        DistinctRequest(
            left_entity_id=first.id,
            right_entity_id=second.id,
            actor="reviewer",
            reason="Registration documents prove separate legal persons.",
        )
    )
    service = IdentifierResolutionService(session)
    service.add(
        first.id,
        IdentifierCreate(
            scheme="registration:gb",
            value="0123-4567",
            source_claim_id=master_claim_factory().id,
        ),
    )
    result = service.add(
        second.id,
        IdentifierCreate(
            scheme="registration:gb",
            value="01234567",
            source_claim_id=master_claim_factory().id,
        ),
    )

    assert result.outcome == "frozen_conflict"
    assert result.conflict_id is not None
    assert session.get(EntityRow, first.id).status == "frozen"
    assert session.get(EntityRow, second.id).status == "frozen"
    assert session.get(IdentityConflictRow, result.conflict_id).status == "open"

    reviewed = service.review_conflict(
        result.conflict_id,
        IdentityConflictReviewRequest(
            action="keep_distinct",
            reviewer="identity-reviewer",
            reason="The shared number is a source error; legal persons remain separate.",
        ),
    )
    assert reviewed.status == "resolved_distinct"
    assert session.get(EntityRow, first.id).status == "active"
    assert session.get(EntityRow, second.id).status == "active"


def test_invalid_lei_is_rejected_before_storage(
    session, master_entity_factory, master_claim_factory
):
    entity = master_entity_factory()

    with pytest.raises(ValueError, match="invalid LEI"):
        IdentifierResolutionService(session).add(
            entity.id,
            IdentifierCreate(
                scheme="lei", value="NOT-A-VALID-LEI", source_claim_id=master_claim_factory().id
            ),
        )


def test_reviewer_can_resolve_identifier_conflict_as_same_entity(
    session, master_entity_factory, master_claim_factory
):
    first = master_entity_factory(name="Merge Candidate A")
    second = master_entity_factory(name="Merge Candidate B")
    ResolutionService(session).mark_distinct(
        DistinctRequest(
            left_entity_id=first.id,
            right_entity_id=second.id,
            actor="initial-reviewer",
            reason="Initial evidence suggested separate entities.",
        )
    )
    service = IdentifierResolutionService(session)
    for entity in (first, second):
        result = service.add(
            entity.id,
            IdentifierCreate(
                scheme="registration:us",
                value="REG-999-001",
                source_claim_id=master_claim_factory().id,
            ),
        )
    assert result.outcome == "frozen_conflict"

    reviewed = service.review_conflict(
        result.conflict_id,
        IdentityConflictReviewRequest(
            action="merge",
            reviewer="senior-identity-reviewer",
            reason="Certified registry extract proves both records are the same legal entity.",
        ),
    )

    assert reviewed.status == "resolved_merged"
    assert reviewed.resolution_json["merge_command_id"]
    assert canonical_root(session, first.id).id == canonical_root(session, second.id).id
