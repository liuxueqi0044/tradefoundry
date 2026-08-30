from tradefoundry.master.contracts import RelationCreate
from tradefoundry.master.relations import RelationService
from tradefoundry.opportunity.participants import ParticipantDiscoveryService


def test_participants_require_direct_roles_or_typed_evidence_paths(
    session, master_claim_factory, master_entity_factory, world_event_factory
):
    project = master_entity_factory(name="Water Project", entity_type="project")
    buyer = master_entity_factory(name="Water Authority")
    epc = master_entity_factory(name="Engineering Contractor")
    affiliate = master_entity_factory(name="Unrelated Affiliate")
    relation_service = RelationService(session)
    buyer_relation = relation_service.create(
        RelationCreate(
            subject_entity_id=buyer.id,
            relation_type="buyer_for",
            object_entity_id=project.id,
            evidence_claim_id=master_claim_factory(value="buyer", verified=True).id,
            confidence=0.97,
            review_status="verified",
        )
    )
    relation_service.create(
        RelationCreate(
            subject_entity_id=epc.id,
            relation_type="epc_for",
            object_entity_id=project.id,
            evidence_claim_id=master_claim_factory(value="epc", verified=True).id,
            confidence=0.91,
            review_status="verified",
        )
    )
    relation_service.create(
        RelationCreate(
            subject_entity_id=affiliate.id,
            relation_type="affiliate_of",
            object_entity_id=project.id,
            evidence_claim_id=master_claim_factory(value="affiliate", verified=True).id,
            confidence=0.99,
            review_status="verified",
        )
    )
    event = world_event_factory(
        event_type="project_approval",
        subject=project,
        subject_role="project",
        field_path="project.approval",
    )

    participants = ParticipantDiscoveryService(session).discover(event.id)
    by_role = {participant.role: participant for participant in participants}

    assert by_role["buyer"].entity_id == buyer.id
    assert by_role["buyer"].hop_distance == 1
    assert buyer_relation.evidence_claim_id in by_role["buyer"].evidence_claim_ids_json
    assert by_role["epc"].entity_id == epc.id
    assert affiliate.id not in {participant.entity_id for participant in participants}
