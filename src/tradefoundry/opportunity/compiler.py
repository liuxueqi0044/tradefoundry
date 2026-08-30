from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import ProductConceptRow
from tradefoundry.opportunity.contracts import CompileRequest, HypothesisView
from tradefoundry.opportunity.models import (
    CompilerRunRow,
    OpportunityTemplateRow,
    ProductNeedRow,
    TradeHypothesisRow,
    WorldEventClaimRow,
    WorldEventRow,
)
from tradefoundry.opportunity.needs import ProductNeedService
from tradefoundry.opportunity.participants import ParticipantDiscoveryService
from tradefoundry.opportunity.routes import RouteCandidateService
from tradefoundry.opportunity.signals import SignalClassifier
from tradefoundry.opportunity.templates import OpportunityTemplateService

COMPILER_VERSION = "opportunity-compiler-v1"


class OpportunityCompiler:
    def __init__(self, session: Session):
        self.session = session

    def compile(self, request: CompileRequest) -> list[HypothesisView]:
        started = perf_counter()
        input_payload = request.model_dump(mode="json", exclude={"correlation_id"})
        input_hash = payload_hash(input_payload)
        metrics: dict[str, int] = {}
        try:
            event = self.session.get(WorldEventRow, request.event_id)
            if event is None:
                raise LookupError(f"world event {request.event_id} not found")
            template = self.session.get(OpportunityTemplateRow, request.template_id)
            if template is None:
                raise LookupError(f"opportunity template {request.template_id} not found")
            if template.status != "active":
                raise ValueError("only an active opportunity template can compile a new hypothesis")
            signals = SignalClassifier(self.session).classify(event.id)
            applicable_ids = {
                item.id for item in OpportunityTemplateService(self.session).applicable(event.id)
            }
            if template.id not in applicable_ids:
                raise ValueError("opportunity template is not applicable to this event")
            needs = ProductNeedService(self.session).derive(event.id, template.id)
            if not needs:
                raise ValueError("template and event produced no product need candidate")
            participants = ParticipantDiscoveryService(self.session).discover(event.id)
            routes = RouteCandidateService(self.session).generate(event.id)
            metrics = {
                "signal_count": len(signals),
                "product_need_count": len(needs),
                "participant_count": len(participants),
                "route_count": len(routes),
                "feasible_route_count": sum(route.feasibility == "feasible" for route in routes),
            }
            hypotheses = [
                self._compile_one(event, template, need.id, request, participants, routes)
                for need in needs
            ]
            metrics["hypothesis_count"] = len(hypotheses)
            self._record_run(
                input_hash,
                request.correlation_id,
                "completed",
                started,
                metrics,
            )
            return [HypothesisView.model_validate(row) for row in hypotheses]
        except Exception as exc:
            self.session.rollback()
            self._record_run(
                input_hash,
                request.correlation_id,
                "failed",
                started,
                metrics,
                type(exc).__name__,
            )
            raise

    def _compile_one(
        self,
        event: WorldEventRow,
        template: OpportunityTemplateRow,
        need_id: str,
        request: CompileRequest,
        participants,
        routes,
    ) -> TradeHypothesisRow:
        need = self.session.get(ProductNeedRow, need_id)
        if need is None:
            raise LookupError(f"product need {need_id} not found")
        product = self.session.get(ProductConceptRow, need.product_concept_id)
        if product is None:
            raise LookupError(f"product concept {need.product_concept_id} not found")
        event_claim_ids = self.session.scalars(
            select(WorldEventClaimRow.claim_id).where(WorldEventClaimRow.event_id == event.id)
        ).all()
        buyers = [candidate for candidate in participants if candidate.role == "buyer"]
        suppliers = [
            candidate for candidate in participants if candidate.role in {"supplier", "awardee"}
        ]
        supporting_claim_ids = sorted(
            {
                *event_claim_ids,
                *need.supporting_claim_ids_json,
                *(
                    claim_id
                    for participant in participants
                    for claim_id in participant.evidence_claim_ids_json
                ),
            }
        )
        explicit = need.basis_type == "explicit_claim"
        statement = (
            f"Verified event evidence states a need for {product.preferred_label}."
            if explicit
            else f"The {event.event_type} event may create a need for {product.preferred_label}."
        )
        facts = [
            {
                "kind": "world_event",
                "event_id": event.id,
                "event_type": event.event_type,
                "title": event.title,
                "claim_ids": sorted(event_claim_ids),
            }
        ]
        inferences = (
            []
            if explicit
            else [
                {
                    "kind": "product_need_candidate",
                    "product_need_id": need.id,
                    "product_concept_id": product.id,
                    "derivation_chain": need.derivation_chain_json,
                    "uncertainty": need.uncertainty,
                }
            ]
        )
        unknowns = set(request.additional_unknowns)
        if not buyers:
            unknowns.add("Buyer identity is not yet evidence-backed.")
        if not suppliers:
            unknowns.add("Supplier capability has not been verified.")
        for route in routes:
            unknowns.update(route.missing_requirements_json)
        if explicit:
            low, high = max(0.05, need.confidence - 0.15), min(0.98, need.confidence + 0.08)
        else:
            low, high = max(0.05, need.confidence - 0.25), min(0.85, need.confidence + 0.15)
        if low >= high:
            low, high = max(0.0, high - 0.05), high
        probe_actions = [
            {
                "action": "review_source_evidence",
                "purpose": "Confirm event currency, scope and deadline.",
                "external_side_effect": False,
                "cost_class": "internal_review",
            },
            {
                "action": "verify_participant_role",
                "purpose": "Resolve buyer/EPC/supplier role gaps before any contact.",
                "external_side_effect": False,
                "cost_class": "internal_research",
            },
        ]
        stop_conditions = [
            "Stop if the event expires or is revoked before validation.",
            "Stop if verified counter-evidence disproves the product need.",
            "Stop if policy marks the product or jurisdiction prohibited.",
            "Stop if no feasible route remains after evidence review.",
        ]
        fingerprint_payload = {
            "event_id": event.id,
            "template_id": template.id,
            "product_need_id": need.id,
            "participants": sorted(candidate.id for candidate in participants),
            "routes": sorted(route.id for route in routes),
            "counter_evidence": request.counter_evidence,
            "unknowns": sorted(unknowns),
            "risks": sorted(set(request.risks)),
            "numeric_assertions": [
                assertion.model_dump(mode="json") for assertion in request.numeric_assertions
            ],
            "compiler_version": COMPILER_VERSION,
        }
        fingerprint = payload_hash(fingerprint_payload)
        existing = self.session.scalar(
            select(TradeHypothesisRow).where(TradeHypothesisRow.fingerprint == fingerprint)
        )
        if existing is not None:
            return existing
        row = TradeHypothesisRow(
            id=str(uuid4()),
            fingerprint=fingerprint,
            statement=statement,
            event_ids_json=[event.id],
            template_id=template.id,
            product_need_ids_json=[need.id],
            buyer_candidate_ids_json=sorted(candidate.id for candidate in buyers),
            supplier_candidate_ids_json=sorted(candidate.id for candidate in suppliers),
            route_candidate_ids_json=sorted(route.id for route in routes),
            fact_assertions_json=facts,
            inference_assertions_json=inferences,
            supporting_claim_ids_json=supporting_claim_ids,
            counter_evidence_json=request.counter_evidence,
            unknowns_json=sorted(unknowns),
            risks_json=sorted(set(request.risks)),
            probability_low=round(low, 6),
            probability_high=round(high, 6),
            probe_actions_json=probe_actions,
            stop_conditions_json=stop_conditions,
            numeric_assertions_json=[
                assertion.model_dump(mode="json") for assertion in request.numeric_assertions
            ],
            compiler_version=COMPILER_VERSION,
            audit_status="pending",
            correlation_id=request.correlation_id,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def _record_run(
        self,
        input_hash: str,
        correlation_id: str,
        status: str,
        started: float,
        metrics: dict,
        error_type: str | None = None,
    ) -> None:
        self.session.add(
            CompilerRunRow(
                id=str(uuid4()),
                input_hash=input_hash,
                compiler_version=COMPILER_VERSION,
                correlation_id=correlation_id,
                status=status,
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                metrics_json=metrics,
                error_type=error_type,
            )
        )
        self.session.commit()

    def get(self, hypothesis_id: str) -> HypothesisView:
        row = self.session.get(TradeHypothesisRow, hypothesis_id)
        if row is None:
            raise LookupError(f"trade hypothesis {hypothesis_id} not found")
        return HypothesisView.model_validate(row)
