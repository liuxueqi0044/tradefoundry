from tradefoundry.master.contracts import MergeRequest, RelationCreate, SplitRequest
from tradefoundry.master.entities import EntityService
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.relations import RelationService
from tradefoundry.master.resolution import ResolutionService


def test_merge_is_reversible_and_golden_fields_explain_provenance(
    session, master_entity_factory, master_claim_factory
):
    unverified_claim = master_claim_factory(value="old address")
    verified_claim = master_claim_factory(value="verified address", verified=True)
    first = master_entity_factory(
        name="Acme Old",
        claim_id=unverified_claim.id,
        attributes={"address": "1 Old Road"},
        priority=100,
    )
    second = master_entity_factory(
        name="Acme Current",
        claim_id=verified_claim.id,
        attributes={"address": "2 New Street"},
        priority=10,
    )
    service = ResolutionService(session)
    command = service.merge(
        MergeRequest(
            winner_entity_id=first.id,
            loser_entity_id=second.id,
            idempotency_key="merge:golden:1",
            actor="reviewer",
            reason="Corporate registry and source documents confirm identity.",
        )
    )
    profile = EntityService(session).profile(first.id)

    assert profile.member_ids == sorted([first.id, second.id])
    assert profile.golden_fields["address"].value == "2 new st"
    assert profile.golden_fields["address"].source_claim_id == verified_claim.id
    assert "claim=verified" in profile.golden_fields["address"].selection_reason
    assert profile.golden_fields["name"].raw_value == "Acme Current"

    undone = service.undo_merge(
        command.id, actor="reviewer", reason="Later registry evidence disproved the merge."
    )
    assert undone.status == "undone"
    assert canonical_root(session, first.id).id != canonical_root(session, second.id).id


def test_split_command_detaches_member_without_deleting_source_entity(
    session, master_entity_factory, master_claim_factory
):
    first = master_entity_factory(name="One")
    second = master_entity_factory(name="Two")
    project = master_entity_factory(name="Project", entity_type="project")
    relation = RelationService(session).create(
        RelationCreate(
            subject_entity_id=second.id,
            relation_type="buyer_for",
            object_entity_id=project.id,
            evidence_claim_id=master_claim_factory().id,
            confidence=0.8,
        )
    )
    service = ResolutionService(session)
    service.merge(
        MergeRequest(
            winner_entity_id=first.id,
            loser_entity_id=second.id,
            idempotency_key="merge:split:1",
            actor="reviewer",
            reason="Fixture merge.",
        )
    )
    split = service.split(
        second.id,
        SplitRequest(
            idempotency_key="split:1",
            actor="reviewer",
            reason="These records belong to separate companies.",
        ),
    )

    assert split.previous_canonical_entity_id == first.id
    assert canonical_root(session, second.id).id == second.id
    assert EntityService(session).profile(second.id).aliases[0].raw_value == "Two"
    assert RelationService(session).traverse(second.id)[0].steps[0].relation.id == relation.id
