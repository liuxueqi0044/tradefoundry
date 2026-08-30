from datetime import UTC, datetime

import pytest

from tradefoundry.master.contracts import RelationCreate
from tradefoundry.master.relations import RelationService


def test_business_graph_supports_three_hops_with_evidence_confidence_and_time(
    session, master_entity_factory, master_claim_factory
):
    parent = master_entity_factory(name="Parent Corp")
    subsidiary = master_entity_factory(name="Subsidiary Ltd")
    project = master_entity_factory(name="Metro Project", entity_type="project")
    award = master_entity_factory(name="Package Award", entity_type="award")
    service = RelationService(session)
    relations = [
        (parent.id, "parent_of", subsidiary.id),
        (subsidiary.id, "epc_for", project.id),
        (project.id, "has_award", award.id),
    ]
    claim_ids = []
    for subject, relation_type, object_ in relations:
        claim = master_claim_factory(value=relation_type, verified=True)
        claim_ids.append(claim.id)
        service.create(
            RelationCreate(
                subject_entity_id=subject,
                relation_type=relation_type,
                object_entity_id=object_,
                evidence_claim_id=claim.id,
                confidence=0.9,
                review_status="verified",
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    paths = service.traverse(
        parent.id, max_depth=3, as_of=datetime(2026, 8, 30, tzinfo=UTC), direction="outgoing"
    )
    deepest = next(path for path in paths if path.end_entity_id == award.id)

    assert len(deepest.steps) == 3
    assert [step.relation.evidence_claim_id for step in deepest.steps] == claim_ids
    assert all(step.relation.confidence == 0.9 for step in deepest.steps)


def test_expired_relation_is_excluded_and_duplicate_is_idempotent(
    session, master_entity_factory, master_claim_factory
):
    buyer = master_entity_factory(name="Buyer")
    project = master_entity_factory(name="Old Project", entity_type="project")
    claim = master_claim_factory()
    request = RelationCreate(
        subject_entity_id=buyer.id,
        relation_type="buyer_for",
        object_entity_id=project.id,
        evidence_claim_id=claim.id,
        confidence=1,
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
        valid_to=datetime(2026, 1, 1, tzinfo=UTC),
    )
    service = RelationService(session)
    first = service.create(request)
    repeated = service.create(request)

    assert first.id == repeated.id
    assert service.traverse(buyer.id, as_of=datetime(2026, 8, 30, tzinfo=UTC)) == []


def test_verified_relation_requires_verified_claim(
    session, master_entity_factory, master_claim_factory
):
    left = master_entity_factory(name="Left")
    right = master_entity_factory(name="Right")
    claim = master_claim_factory()

    with pytest.raises(ValueError, match="verified evidence Claim"):
        RelationService(session).create(
            RelationCreate(
                subject_entity_id=left.id,
                relation_type="parent_of",
                object_entity_id=right.id,
                evidence_claim_id=claim.id,
                confidence=1,
                review_status="verified",
            )
        )
