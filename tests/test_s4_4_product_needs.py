import pytest
from sqlalchemy import select

from tradefoundry.opportunity.contracts import LLMProductNeedProposal
from tradefoundry.opportunity.models import WorldEventClaimRow
from tradefoundry.opportunity.needs import ProductNeedService
from tradefoundry.opportunity.signals import SignalClassifier


def test_explicit_product_claim_is_not_downgraded_to_an_inference(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    product = product_concept_factory(label="Ball Valve")
    event = world_event_factory(product_concept_id=product.id)
    template = opportunity_template_factory(product_concept_id=product.id)
    SignalClassifier(session).classify(event.id)

    needs = ProductNeedService(session).derive(event.id, template.id)

    assert len(needs) == 1
    assert needs[0].basis_type == "explicit_claim"
    assert needs[0].confidence == 0.94
    assert needs[0].derivation_chain_json[0]["kind"] == "verified_claim"


def test_project_template_derives_uncertain_product_with_a_reproducible_chain(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    product = product_concept_factory(label="Water Treatment Valve")
    event = world_event_factory(
        event_type="project_approval",
        title="Approved municipal water project",
        subject_role="project",
        field_path="project.approval",
        value="The municipal water project is approved.",
    )
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["project_approval"],
        signal_types=["project_approval"],
        required_claim_fields=["project.approval"],
        product_need_rules=[
            {
                "product_concept_id": product.id,
                "basis": "Approved water projects commonly require flow-control equipment.",
                "confidence": 0.62,
                "uncertainty": "No bill of quantities names the valve yet.",
                "applicable_event_types": ["project_approval"],
                "applicable_signal_types": ["project_approval"],
                "required_claim_fields": ["project.approval"],
            }
        ],
    )
    SignalClassifier(session).classify(event.id)

    needs = ProductNeedService(session).derive(event.id, template.id)

    assert needs[0].basis_type == "template_inference"
    assert needs[0].confidence == 0.62
    assert "No bill of quantities" in needs[0].uncertainty
    assert needs[0].derivation_chain_json[0]["template_version"] == 1
    assert needs[0].supporting_claim_ids_json


def test_llm_product_proposal_is_evidence_bounded_versioned_and_never_a_fact(
    session,
    master_claim_factory,
    product_concept_factory,
    world_event_factory,
    opportunity_template_factory,
):
    product = product_concept_factory(label="Pressure Control Valve")
    event = world_event_factory(
        event_type="project_approval",
        subject_role="project",
        field_path="project.approval",
    )
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["project_approval"],
    )
    event_claim_id = session.scalar(
        select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event.id)
    )
    request = LLMProductNeedProposal(
        idempotency_key="llm-need-proposal-1",
        product_concept_id=product.id,
        confidence=0.58,
        uncertainty="The bill of quantities is not available.",
        reasoning_summary="Project scope suggests pressure-control equipment.",
        supporting_claim_ids=[event_claim_id],
        model_name="provider-neutral-model",
        prompt_version="need-proposal-v1",
    )
    service = ProductNeedService(session)
    proposal = service.propose(event.id, template.id, request)
    repeated = service.propose(event.id, template.id, request)

    assert repeated.id == proposal.id
    assert proposal.basis_type == "llm_proposal"
    assert proposal.derivation_chain_json[0]["prompt_version"] == "need-proposal-v1"
    assert service.derive(event.id, template.id)[0].id == proposal.id

    outside_claim = master_claim_factory(value="outside", verified=True)
    with pytest.raises(ValueError, match="outside the WorldEvent"):
        service.propose(
            event.id,
            template.id,
            request.model_copy(
                update={
                    "idempotency_key": "llm-need-proposal-outside",
                    "supporting_claim_ids": [outside_claim.id],
                }
            ),
        )
