from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.master.models import EntityRow


def canonical_root(session: Session, entity_id: str) -> EntityRow:
    entity = session.get(EntityRow, entity_id)
    if entity is None:
        raise LookupError(f"entity {entity_id} not found")
    visited: set[str] = set()
    while entity.canonical_entity_id is not None:
        if entity.id in visited:
            raise RuntimeError("canonical entity cycle detected")
        visited.add(entity.id)
        parent = session.get(EntityRow, entity.canonical_entity_id)
        if parent is None:
            raise RuntimeError(f"canonical entity {entity.canonical_entity_id} is missing")
        entity = parent
    return entity


def canonical_member_ids(session: Session, canonical_id: str) -> list[str]:
    root = canonical_root(session, canonical_id)
    entities = session.scalars(select(EntityRow)).all()
    return sorted(
        entity.id for entity in entities if canonical_root(session, entity.id).id == root.id
    )
