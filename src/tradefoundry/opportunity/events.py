from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import canonical_json_bytes, payload_hash
from tradefoundry.master.identity import canonical_root
from tradefoundry.master.models import EntityRow, ProductConceptRow
from tradefoundry.opportunity.contracts import WorldEventCreate, WorldEventView
from tradefoundry.opportunity.evidence import require_verified_claim
from tradefoundry.opportunity.models import (
    WorldEventClaimRow,
    WorldEventProductRow,
    WorldEventRow,
    WorldEventSubjectRow,
)


class WorldEventService:
    def __init__(self, session: Session):
        self.session = session

    def build(self, request: WorldEventCreate) -> WorldEventView:
        claims = {
            claim_id: require_verified_claim(self.session, claim_id)
            for claim_id in request.evidence_claim_ids
        }
        subjects = []
        for subject in request.subjects:
            entity = self.session.get(EntityRow, subject.entity_id)
            if entity is None:
                raise LookupError(f"entity {subject.entity_id} not found")
            subjects.append(
                {
                    "entity_id": subject.entity_id,
                    "canonical_entity_id": canonical_root(self.session, subject.entity_id).id,
                    "role": subject.role,
                    "claim_id": subject.claim_id,
                }
            )
        products = []
        for product in request.products:
            if self.session.get(ProductConceptRow, product.product_concept_id) is None:
                raise LookupError(f"product concept {product.product_concept_id} not found")
            products.append(product.model_dump(mode="json"))
        if (
            request.location_entity_id is not None
            and self.session.get(EntityRow, request.location_entity_id) is None
        ):
            raise LookupError(f"location entity {request.location_entity_id} not found")

        claim_facts = sorted(
            (
                {
                    "subject_key": claim.subject_key,
                    "field_path": claim.field_path,
                    "value": claim.normalized_value_json
                    if claim.normalized_value_json is not None
                    else claim.value_json,
                    "unit": claim.unit,
                    "currency": claim.currency,
                    "valid_from": claim.valid_from,
                    "valid_to": claim.valid_to,
                }
                for claim in claims.values()
            ),
            key=payload_hash,
        )
        facts_snapshot = {
            "title": request.title.strip(),
            "event_type": request.event_type.value,
            "occurred_at": request.occurred_at,
            "expires_at": request.expires_at,
            "country_code": request.country_code,
            "location_entity_id": request.location_entity_id,
            "subjects": sorted(subjects, key=payload_hash),
            "products": sorted(products, key=payload_hash),
            "claim_facts": claim_facts,
        }
        fingerprint = payload_hash(facts_snapshot)
        json_facts_snapshot = json.loads(canonical_json_bytes(facts_snapshot))
        existing = self.session.scalar(
            select(WorldEventRow).where(WorldEventRow.fingerprint == fingerprint)
        )
        if existing is not None:
            return WorldEventView.model_validate(existing)

        event = WorldEventRow(
            id=str(uuid4()),
            fingerprint=fingerprint,
            title=request.title.strip(),
            event_type=request.event_type.value,
            occurred_at=request.occurred_at,
            expires_at=request.expires_at,
            country_code=request.country_code,
            location_entity_id=request.location_entity_id,
            reliability=request.reliability,
            status="active",
            facts_snapshot_json=json_facts_snapshot,
            metadata_json=request.metadata,
            correlation_id=request.correlation_id,
        )
        self.session.add(event)
        self.session.flush()
        self.session.add_all(
            WorldEventClaimRow(id=str(uuid4()), event_id=event.id, claim_id=claim_id)
            for claim_id in sorted(claims)
        )
        self.session.add_all(
            WorldEventSubjectRow(
                id=str(uuid4()),
                event_id=event.id,
                entity_id=subject.entity_id,
                role=subject.role,
                claim_id=subject.claim_id,
            )
            for subject in request.subjects
        )
        self.session.add_all(
            WorldEventProductRow(
                id=str(uuid4()),
                event_id=event.id,
                product_concept_id=product.product_concept_id,
                certainty=product.certainty,
                claim_id=product.claim_id,
            )
            for product in request.products
        )
        self.session.commit()
        return WorldEventView.model_validate(event)

    def get(self, event_id: str) -> WorldEventView:
        row = self.session.get(WorldEventRow, event_id)
        if row is None:
            raise LookupError(f"world event {event_id} not found")
        return WorldEventView.model_validate(row)
