from tradefoundry.master.contracts import (
    ProductConceptCreate,
    RequirementInput,
    SpecificationCreate,
)
from tradefoundry.master.products import ProductOntologyService
from tradefoundry.master.specifications import ProductSpecificationService


def _concept(session, claim_factory):
    claim = claim_factory(value="steel pipe")
    return ProductOntologyService(session).create(
        ProductConceptCreate(
            concept_key="steel-pipe",
            preferred_label="Steel Pipe",
            source_claim_id=claim.id,
        )
    )


def test_specifications_support_required_optional_range_tolerance_and_units(
    session, master_claim_factory
):
    concept = _concept(session, master_claim_factory)
    claim = master_claim_factory(value="specification one")
    service = ProductSpecificationService(session)
    specification = service.create(
        SpecificationCreate(
            specification_key="pipe-spec:v1",
            concept_id=concept.id,
            version_no=1,
            original_text="Weight 1000 g; length 5-10 m; diameter 20 mm ± 0.5 mm.",
            source_claim_id=claim.id,
            requirements=[
                RequirementInput(
                    requirement_key="weight",
                    mode="required",
                    value="1000",
                    unit="g",
                    target_unit="kg",
                    original_text="Weight 1000 g",
                ),
                RequirementInput(
                    requirement_key="length",
                    mode="range",
                    value={"min": "5", "max": "10"},
                    unit="m",
                    original_text="Length 5-10 m",
                ),
                RequirementInput(
                    requirement_key="diameter",
                    mode="tolerance",
                    value={"target": "20", "tolerance": "0.5"},
                    unit="mm",
                    original_text="Diameter 20 mm ± 0.5 mm",
                ),
                RequirementInput(
                    requirement_key="color",
                    mode="optional",
                    value="blue",
                    original_text="Blue preferred",
                ),
            ],
        )
    )
    by_key = {item.requirement_key: item for item in specification.requirements}

    assert by_key["weight"].normalized_value_json == {"amount": "1.000", "unit": "kg"}
    assert by_key["length"].normalized_value_json == {
        "min": "5",
        "max": "10",
        "unit": "m",
    }
    assert by_key["diameter"].normalized_value_json["tolerance"] == "0.0005"
    assert by_key["color"].mode == "optional"
    assert "±" in specification.original_text


def test_specification_diff_preserves_original_and_marks_changes(session, master_claim_factory):
    concept = _concept(session, master_claim_factory)
    service = ProductSpecificationService(session)
    first_claim = master_claim_factory()
    second_claim = master_claim_factory()
    first = service.create(
        SpecificationCreate(
            specification_key="diff:v1",
            concept_id=concept.id,
            version_no=1,
            original_text="Weight 1000 g",
            source_claim_id=first_claim.id,
            requirements=[
                RequirementInput(
                    requirement_key="weight",
                    mode="required",
                    value="1000",
                    unit="g",
                    target_unit="kg",
                    original_text="Weight 1000 g",
                )
            ],
        )
    )
    second = service.create(
        SpecificationCreate(
            specification_key="diff:v2",
            concept_id=concept.id,
            version_no=2,
            original_text="Weight 1.2 kg and blue finish",
            source_claim_id=second_claim.id,
            requirements=[
                RequirementInput(
                    requirement_key="weight",
                    mode="required",
                    value="1.2",
                    unit="kg",
                    target_unit="kg",
                    original_text="Weight 1.2 kg",
                ),
                RequirementInput(
                    requirement_key="color",
                    mode="optional",
                    value="blue",
                    original_text="Blue finish",
                ),
            ],
        )
    )
    differences = {item.requirement_key: item for item in service.diff(first.id, second.id)}

    assert differences["weight"].change_type == "changed"
    assert differences["weight"].left.original_text == "Weight 1000 g"
    assert differences["weight"].right.original_text == "Weight 1.2 kg"
    assert differences["color"].change_type == "added"
