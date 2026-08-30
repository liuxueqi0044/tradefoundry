from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.opportunity.contracts import AuditRequest, AuditView
from tradefoundry.opportunity.evidence import require_verified_claim
from tradefoundry.opportunity.models import (
    HypothesisAuditRow,
    OpportunityTemplateRow,
    RouteCandidateRow,
    TradeHypothesisRow,
    WorldEventRow,
)

AUDITOR_VERSION = "hypothesis-auditor-v1"
_REJECT_FLAGS = {"embargoed", "prohibited_product", "confirmed_sanctions_match"}
_REVIEW_FLAGS = {"possible_sanctions_match", "unknown_export_control"}


class HypothesisAuditor:
    def __init__(self, session: Session):
        self.session = session

    def audit(self, hypothesis_id: str, request: AuditRequest) -> AuditView:
        request_hash = payload_hash(
            {"hypothesis_id": hypothesis_id, **request.model_dump(mode="json")}
        )
        existing = self.session.scalar(
            select(HypothesisAuditRow).where(
                HypothesisAuditRow.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValueError("audit idempotency key was reused with a different payload")
            return AuditView.model_validate(existing)
        hypothesis = self.session.get(TradeHypothesisRow, hypothesis_id)
        if hypothesis is None:
            raise LookupError(f"trade hypothesis {hypothesis_id} not found")
        template = self.session.get(OpportunityTemplateRow, hypothesis.template_id)
        if template is None:
            raise RuntimeError(f"template {hypothesis.template_id} is missing")
        at = request.as_of or datetime.now(UTC)
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)

        reasons: list[str] = []
        needs_data: list[str] = []
        evidence_failures: list[str] = []
        for claim_id in hypothesis.supporting_claim_ids_json:
            try:
                require_verified_claim(self.session, claim_id)
            except (LookupError, ValueError) as exc:
                evidence_failures.append(str(exc))
        if not hypothesis.supporting_claim_ids_json:
            evidence_failures.append("hypothesis has no supporting evidence Claim")
        if evidence_failures:
            reasons.extend(evidence_failures)

        unsupported_numbers = [
            assertion.get("label", "unnamed numeric assertion")
            for assertion in hypothesis.numeric_assertions_json
            if not assertion.get("claim_id")
            or assertion.get("claim_id") not in hypothesis.supporting_claim_ids_json
        ]
        if unsupported_numbers:
            reasons.append(
                "numeric assertions lack cited supporting Claims: "
                + ", ".join(sorted(unsupported_numbers))
            )

        events = [
            self.session.get(WorldEventRow, event_id) for event_id in hypothesis.event_ids_json
        ]
        missing_events = [
            event_id
            for event_id, event in zip(hypothesis.event_ids_json, events, strict=True)
            if event is None
        ]
        if missing_events:
            reasons.append("world events are missing: " + ", ".join(missing_events))
        expired_events = [
            event.id
            for event in events
            if event is not None
            and (
                event.status != "active"
                or (event.expires_at and self._aware(event.expires_at) <= at)
            )
        ]
        if expired_events:
            reasons.append("demand event is expired or inactive: " + ", ".join(expired_events))

        policy_flags = set(request.policy_flags)
        rejected_flags = sorted(policy_flags.intersection(_REJECT_FLAGS))
        if rejected_flags:
            reasons.append("hard policy prohibition: " + ", ".join(rejected_flags))
        review_flags = sorted(policy_flags.intersection(_REVIEW_FLAGS))
        if review_flags:
            needs_data.append("policy review required: " + ", ".join(review_flags))

        contexts = [
            {
                "event_type": event.event_type,
                "country_code": event.country_code,
                "policy_flags": sorted(policy_flags),
                **event.metadata_json,
            }
            for event in events
            if event is not None
        ]
        for condition in template.forbidden_conditions_json:
            if any(self._condition_matches(condition, context) for context in contexts):
                reasons.append(f"template prohibition: {condition['reason']}")

        dispositive_counter = [
            item
            for item in hypothesis.counter_evidence_json
            if item.get("status") == "verified" and item.get("severity") == "dispositive"
        ]
        if dispositive_counter:
            reasons.append("verified counter-evidence disproves the hypothesis")
        elif hypothesis.counter_evidence_json:
            needs_data.append("counter-evidence requires resolution")

        routes = [
            self.session.get(RouteCandidateRow, route_id)
            for route_id in hypothesis.route_candidate_ids_json
        ]
        feasible_routes = [route for route in routes if route and route.feasibility == "feasible"]
        if not feasible_routes:
            needs_data.append("no evidence-backed feasible Deal Route")
        if not hypothesis.buyer_candidate_ids_json:
            needs_data.append("no evidence-backed buyer candidate")

        decision = "reject" if reasons else "needs_data" if needs_data else "pass"
        all_reasons = (
            reasons
            if reasons
            else needs_data
            if needs_data
            else ["Evidence, currency, policy and route gates passed."]
        )
        checks = {
            "verified_evidence": not evidence_failures,
            "numeric_claim_citations": not unsupported_numbers,
            "event_current": not expired_events and not missing_events,
            "hard_policy_clear": not rejected_flags,
            "template_prohibitions_clear": not any(
                reason.startswith("template prohibition:") for reason in reasons
            ),
            "counter_evidence_clear": not dispositive_counter,
            "feasible_route_count": len(feasible_routes),
            "buyer_candidate_count": len(hypothesis.buyer_candidate_ids_json),
        }
        row = HypothesisAuditRow(
            id=str(uuid4()),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            hypothesis_id=hypothesis.id,
            decision=decision,
            reasons_json=all_reasons,
            checks_json=checks,
            policy_version=request.policy_version,
            auditor_version=AUDITOR_VERSION,
            actor=request.actor,
        )
        hypothesis.audit_status = decision
        self.session.add(row)
        self.session.commit()
        return AuditView.model_validate(row)

    @staticmethod
    def _condition_matches(condition: dict, context: dict) -> bool:
        actual = context.get(condition.get("field"))
        expected = condition.get("value")
        operator = condition.get("operator")
        if operator == "equals":
            return actual == expected
        if operator == "contains":
            return actual is not None and expected in actual
        if operator == "in":
            return isinstance(expected, list) and actual in expected
        return False

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
