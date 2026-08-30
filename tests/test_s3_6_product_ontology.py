from tradefoundry.master.contracts import (
    ProductCodeCreate,
    ProductCodeReview,
    ProductConceptCreate,
    ProductSynonymCreate,
)
from tradefoundry.master.products import ProductOntologyService


def test_product_hierarchy_synonyms_and_code_candidates_remain_explicit(
    session, master_claim_factory
):
    service = ProductOntologyService(session)
    root_claim = master_claim_factory(value="industrial valves")
    root = service.create(
        ProductConceptCreate(
            concept_key="industrial-valves",
            preferred_label="Industrial Valves",
            source_claim_id=root_claim.id,
        )
    )
    child_claim = master_claim_factory(value="ball valves")
    child = service.create(
        ProductConceptCreate(
            concept_key="ball-valves",
            preferred_label="Ball Valves",
            parent_id=root.id,
            source_claim_id=child_claim.id,
        )
    )
    service.add_synonym(
        child.id,
        ProductSynonymCreate(
            label="球阀", language="zh", source_claim_id=master_claim_factory().id
        ),
    )
    mapping = service.add_code(
        child.id,
        ProductCodeCreate(
            scheme="hs",
            code="8481.80",
            confidence=0.72,
            method="classifier-v1",
            source_claim_id=master_claim_factory().id,
        ),
    )

    assert child.parent_id == root.id
    assert mapping.status == "candidate"
    assert mapping.code == "8481.80"
    assert service.search("球阀")[0][0].id == child.id

    verified = service.review_code(
        mapping.id,
        ProductCodeReview(
            action="verify",
            reviewer="classification-specialist",
            reason="Confirmed against the product construction and tariff notes.",
        ),
    )
    assert verified.status == "verified"


def test_product_creation_and_synonym_addition_are_idempotent(session, master_claim_factory):
    service = ProductOntologyService(session)
    claim = master_claim_factory()
    request = ProductConceptCreate(
        concept_key="pumps", preferred_label="Pumps", source_claim_id=claim.id
    )
    first = service.create(request)
    repeated = service.create(request)
    synonym_request = ProductSynonymCreate(label="Pump", source_claim_id=master_claim_factory().id)
    synonym = service.add_synonym(first.id, synonym_request)
    same_synonym = service.add_synonym(first.id, synonym_request)

    assert repeated.id == first.id
    assert same_synonym.id == synonym.id
