import pytest

from tradefoundry.opportunity.contracts import TemplateCreate, TemplateStateRequest
from tradefoundry.opportunity.signals import SignalClassifier
from tradefoundry.opportunity.templates import OpportunityTemplateService


def _template_request(product_id: str, idempotency_key: str, name: str) -> TemplateCreate:
    return TemplateCreate(
        template_key="water-project-valves",
        idempotency_key=idempotency_key,
        name=name,
        event_types=["rfq"],
        signal_types=["explicit_rfq"],
        country_codes=["ke"],
        product_concept_ids=[product_id],
        required_claim_fields=["procurement.notice"],
        forbidden_conditions=[
            {
                "field": "policy_flags",
                "operator": "contains",
                "value": "prohibited_product",
                "reason": "The product is prohibited by policy.",
            }
        ],
        created_by="template-owner",
    )


def test_templates_are_versioned_activatable_and_rollbackable(session, product_concept_factory):
    product = product_concept_factory()
    service = OpportunityTemplateService(session)
    first = service.create(_template_request(product.id, "template:v1", "Valve template v1"))
    second = service.create(_template_request(product.id, "template:v2", "Valve template v2"))
    first_active = service.activate(
        first.id, TemplateStateRequest(actor="owner", reason="Initial release.")
    )
    second_active = service.activate(
        second.id, TemplateStateRequest(actor="owner", reason="Promote v2.")
    )

    assert (first.version_no, second.version_no) == (1, 2)
    assert first_active.status == "active"
    assert second_active.status == "active"
    assert service.get(first.id).status == "deprecated"

    rolled_back = service.activate(
        first.id, TemplateStateRequest(actor="owner", reason="Rollback after regression.")
    )
    assert rolled_back.status == "active"
    assert service.get(second.id).status == "deprecated"

    repeated = service.create(_template_request(product.id, "template:v1", "Valve template v1"))
    assert repeated.id == first.id
    with pytest.raises(ValueError, match="idempotency key"):
        service.create(_template_request(product.id, "template:v1", "Changed payload"))


def test_only_matching_active_templates_are_applicable(
    session, product_concept_factory, world_event_factory
):
    product = product_concept_factory()
    event = world_event_factory(product_concept_id=product.id)
    SignalClassifier(session).classify(event.id)
    service = OpportunityTemplateService(session)
    template = service.create(_template_request(product.id, "template:applicable", "Applicable"))
    service.activate(template.id, TemplateStateRequest(actor="owner", reason="Ready."))

    assert [item.id for item in service.applicable(event.id)] == [template.id]
