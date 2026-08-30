from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import ProductConceptRow
from tradefoundry.opportunity.contracts import (
    TemplateCreate,
    TemplateStateRequest,
    TemplateView,
)
from tradefoundry.opportunity.models import (
    EventSignalRow,
    OpportunityTemplateRow,
    TemplateStateChangeRow,
    WorldEventClaimRow,
    WorldEventRow,
)


class OpportunityTemplateService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: TemplateCreate) -> TemplateView:
        request_hash = payload_hash(request.model_dump(mode="json"))
        existing = self.session.scalar(
            select(OpportunityTemplateRow).where(
                OpportunityTemplateRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("template idempotency key was reused with a different payload")
            return TemplateView.model_validate(existing)
        for concept_id in {
            *request.product_concept_ids,
            *(rule.product_concept_id for rule in request.product_need_rules),
        }:
            if self.session.get(ProductConceptRow, concept_id) is None:
                raise LookupError(f"product concept {concept_id} not found")
        current = self.session.scalar(
            select(func.max(OpportunityTemplateRow.version_no)).where(
                OpportunityTemplateRow.template_key == request.template_key
            )
        )
        row = OpportunityTemplateRow(
            id=str(uuid4()),
            template_key=request.template_key,
            version_no=(current or 0) + 1,
            request_hash=request_hash,
            idempotency_key=request.idempotency_key,
            name=request.name,
            description=request.description,
            status="draft",
            event_types_json=sorted(event.value for event in request.event_types),
            signal_types_json=sorted(signal.value for signal in request.signal_types),
            country_codes_json=request.country_codes,
            product_concept_ids_json=sorted(set(request.product_concept_ids)),
            required_claim_fields_json=sorted(set(request.required_claim_fields)),
            forbidden_conditions_json=[
                condition.model_dump(mode="json") for condition in request.forbidden_conditions
            ],
            product_need_rules_json=[
                rule.model_dump(mode="json") for rule in request.product_need_rules
            ],
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return TemplateView.model_validate(row)

    def activate(self, template_id: str, request: TemplateStateRequest) -> TemplateView:
        target = self._get(template_id)
        siblings = self.session.scalars(
            select(OpportunityTemplateRow).where(
                OpportunityTemplateRow.template_key == target.template_key,
                OpportunityTemplateRow.status == "active",
            )
        ).all()
        for sibling in siblings:
            if sibling.id != target.id:
                self._change(sibling, "deprecated", request)
        if target.status != "active":
            self._change(target, "active", request)
        self.session.commit()
        return TemplateView.model_validate(target)

    def deprecate(self, template_id: str, request: TemplateStateRequest) -> TemplateView:
        target = self._get(template_id)
        if target.status != "deprecated":
            self._change(target, "deprecated", request)
            self.session.commit()
        return TemplateView.model_validate(target)

    def applicable(self, event_id: str) -> list[TemplateView]:
        event = self.session.get(WorldEventRow, event_id)
        if event is None:
            raise LookupError(f"world event {event_id} not found")
        signals = set(
            self.session.scalars(
                select(EventSignalRow.signal_type).where(EventSignalRow.event_id == event_id)
            ).all()
        )
        claim_ids = self.session.scalars(
            select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event_id)
        ).all()
        claim_fields = {
            claim.field_path
            for claim_id in claim_ids
            if (claim := self.session.get(ClaimRow, claim_id)) is not None
        }
        templates = self.session.scalars(
            select(OpportunityTemplateRow).where(OpportunityTemplateRow.status == "active")
        ).all()
        return [
            TemplateView.model_validate(template)
            for template in templates
            if event.event_type in template.event_types_json
            and (
                not template.signal_types_json
                or bool(signals.intersection(template.signal_types_json))
            )
            and (
                not template.country_codes_json or event.country_code in template.country_codes_json
            )
            and set(template.required_claim_fields_json).issubset(claim_fields)
        ]

    def get(self, template_id: str) -> TemplateView:
        return TemplateView.model_validate(self._get(template_id))

    def _get(self, template_id: str) -> OpportunityTemplateRow:
        row = self.session.get(OpportunityTemplateRow, template_id)
        if row is None:
            raise LookupError(f"opportunity template {template_id} not found")
        return row

    def _change(
        self,
        row: OpportunityTemplateRow,
        new_status: str,
        request: TemplateStateRequest,
    ) -> None:
        previous = row.status
        row.status = new_status
        self.session.add(
            TemplateStateChangeRow(
                id=str(uuid4()),
                template_id=row.id,
                previous_status=previous,
                new_status=new_status,
                actor=request.actor,
                reason=request.reason,
            )
        )
