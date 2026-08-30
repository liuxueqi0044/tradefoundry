from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import ProductConceptRow
from tradefoundry.opportunity.contracts import (
    LLMProductNeedProposal,
    ProductNeedRule,
    ProductNeedView,
)
from tradefoundry.opportunity.evidence import require_verified_claim
from tradefoundry.opportunity.models import (
    EventSignalRow,
    OpportunityTemplateRow,
    ProductNeedRow,
    WorldEventClaimRow,
    WorldEventProductRow,
    WorldEventRow,
)

DERIVATION_VERSION = "product-need-v1"


class ProductNeedService:
    def __init__(self, session: Session):
        self.session = session

    def derive(self, event_id: str, template_id: str) -> list[ProductNeedView]:
        event = self.session.get(WorldEventRow, event_id)
        if event is None:
            raise LookupError(f"world event {event_id} not found")
        template = self.session.get(OpportunityTemplateRow, template_id)
        if template is None:
            raise LookupError(f"opportunity template {template_id} not found")
        signal_types = set(
            self.session.scalars(
                select(EventSignalRow.signal_type).where(EventSignalRow.event_id == event_id)
            ).all()
        )
        claim_ids = self.session.scalars(
            select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event_id)
        ).all()
        claim_by_field: dict[str, list[str]] = {}
        for claim_id in claim_ids:
            claim = self.session.get(ClaimRow, claim_id)
            if claim is not None:
                claim_by_field.setdefault(claim.field_path, []).append(claim.id)
        direct_products = self.session.scalars(
            select(WorldEventProductRow).where(WorldEventProductRow.event_id == event_id)
        ).all()
        proposals: dict[str, dict] = {
            product.product_concept_id: {
                "basis_type": "explicit_claim",
                "confidence": product.certainty,
                "uncertainty": "Product is explicit in verified event evidence.",
                "chain": [
                    {
                        "kind": "verified_claim",
                        "claim_id": product.claim_id,
                        "conclusion": "explicit product need",
                    }
                ],
                "claims": [product.claim_id],
            }
            for product in direct_products
        }
        for raw_rule in template.product_need_rules_json:
            rule = ProductNeedRule.model_validate(raw_rule)
            if rule.applicable_event_types and event.event_type not in {
                value.value for value in rule.applicable_event_types
            }:
                continue
            if rule.applicable_signal_types and not signal_types.intersection(
                value.value for value in rule.applicable_signal_types
            ):
                continue
            if not set(rule.required_claim_fields).issubset(claim_by_field):
                continue
            if rule.product_concept_id in proposals:
                continue
            supporting = sorted(
                {
                    claim_id
                    for field in rule.required_claim_fields
                    for claim_id in claim_by_field.get(field, [])
                }
            )
            proposals[rule.product_concept_id] = {
                "basis_type": "template_inference",
                "confidence": rule.confidence,
                "uncertainty": rule.uncertainty,
                "chain": [
                    {
                        "kind": "template_rule",
                        "template_id": template.id,
                        "template_version": template.version_no,
                        "basis": rule.basis,
                        "event_type": event.event_type,
                        "signal_types": sorted(signal_types),
                        "required_claim_fields": rule.required_claim_fields,
                    }
                ],
                "claims": supporting,
            }
        rows: list[ProductNeedRow] = []
        version = f"{DERIVATION_VERSION}:template-{template.version_no}"
        for concept_id, proposal in sorted(proposals.items()):
            idempotency_key = f"derive:{event_id}:{template_id}:{concept_id}:{version}"
            request_hash = payload_hash(proposal)
            existing = self.session.scalar(
                select(ProductNeedRow).where(
                    ProductNeedRow.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("derived product-need identity changed for the same inputs")
                rows.append(existing)
                continue
            row = ProductNeedRow(
                id=str(uuid4()),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                event_id=event_id,
                template_id=template_id,
                product_concept_id=concept_id,
                basis_type=proposal["basis_type"],
                confidence=proposal["confidence"],
                uncertainty=proposal["uncertainty"],
                derivation_chain_json=proposal["chain"],
                supporting_claim_ids_json=proposal["claims"],
                derivation_version=version,
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        all_rows = self.session.scalars(
            select(ProductNeedRow)
            .where(
                ProductNeedRow.event_id == event_id,
                ProductNeedRow.template_id == template_id,
            )
            .order_by(ProductNeedRow.created_at, ProductNeedRow.id)
        ).all()
        return [ProductNeedView.model_validate(row) for row in all_rows]

    def propose(
        self,
        event_id: str,
        template_id: str,
        request: LLMProductNeedProposal,
    ) -> ProductNeedView:
        if self.session.get(WorldEventRow, event_id) is None:
            raise LookupError(f"world event {event_id} not found")
        if self.session.get(OpportunityTemplateRow, template_id) is None:
            raise LookupError(f"opportunity template {template_id} not found")
        if self.session.get(ProductConceptRow, request.product_concept_id) is None:
            raise LookupError(f"product concept {request.product_concept_id} not found")
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(ProductNeedRow).where(ProductNeedRow.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("proposal idempotency key was reused with a different payload")
            return ProductNeedView.model_validate(existing)
        event_claim_ids = set(
            self.session.scalars(
                select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event_id)
            ).all()
        )
        outside_event = set(request.supporting_claim_ids) - event_claim_ids
        if outside_event:
            raise ValueError("LLM proposal cites Claims outside the WorldEvent evidence set")
        for claim_id in request.supporting_claim_ids:
            require_verified_claim(self.session, claim_id)
        version = f"llm:{request.model_name}:{request.prompt_version}"
        row = ProductNeedRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            event_id=event_id,
            template_id=template_id,
            product_concept_id=request.product_concept_id,
            basis_type="llm_proposal",
            confidence=request.confidence,
            uncertainty=request.uncertainty,
            derivation_chain_json=[
                {
                    "kind": "llm_proposal",
                    "model_name": request.model_name,
                    "prompt_version": request.prompt_version,
                    "reasoning_summary": request.reasoning_summary,
                }
            ],
            supporting_claim_ids_json=sorted(set(request.supporting_claim_ids)),
            derivation_version=version,
        )
        self.session.add(row)
        self.session.commit()
        return ProductNeedView.model_validate(row)
