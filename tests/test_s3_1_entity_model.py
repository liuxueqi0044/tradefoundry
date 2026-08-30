import pytest
from sqlalchemy import func, select

from tradefoundry.master.contracts import EntityCreate
from tradefoundry.master.entities import EntityService
from tradefoundry.master.models import EntityAliasRow, EntityRow


@pytest.mark.parametrize(
    "entity_type",
    ["organization", "person", "project", "procurement", "award", "product", "location"],
)
def test_unified_entity_model_supports_every_initial_domain_type(
    entity_type, master_entity_factory
):
    entity = master_entity_factory(
        name=f"Golden {entity_type}", entity_type=entity_type, key=f"type:{entity_type}"
    )

    assert entity.entity_type == entity_type
    assert entity.status == "active"


def test_entity_creation_is_idempotent_and_keeps_source_alias(session, master_entity_factory):
    first = master_entity_factory(name="Acme Limited", key="stable:acme")
    repeated = master_entity_factory(
        name="Acme Limited", key="stable:acme", claim_id=first.source_claim_id
    )

    assert first.id == repeated.id
    assert session.scalar(select(func.count()).select_from(EntityRow)) == 1
    alias = session.scalar(select(EntityAliasRow))
    assert alias.raw_value == "Acme Limited"
    assert alias.source_claim_id == first.source_claim_id


def test_entity_key_collision_and_missing_evidence_are_rejected(session, master_entity_factory):
    entity = master_entity_factory(name="Original Name", key="collision:key")
    with pytest.raises(ValueError, match="different payload"):
        EntityService(session).create(
            EntityCreate(
                entity_key="collision:key",
                entity_type="organization",
                source_claim_id=entity.source_claim_id,
                primary_name="Different Name",
            )
        )
    with pytest.raises(LookupError, match="Claim missing not found"):
        EntityService(session).create(
            EntityCreate(
                entity_key="missing:claim",
                entity_type="organization",
                source_claim_id="missing",
                primary_name="No Evidence Entity",
            )
        )
