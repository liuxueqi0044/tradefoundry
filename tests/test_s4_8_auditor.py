from datetime import UTC, datetime

from tradefoundry.opportunity.auditor import HypothesisAuditor
from tradefoundry.opportunity.compiler import OpportunityCompiler
from tradefoundry.opportunity.contracts import AuditRequest, CompileRequest


def _compile_explicit(
    session,
    product_concept_factory,
    world_event_factory,
    opportunity_template_factory,
    *,
    numeric_assertions=None,
    forbidden_conditions=None,
):
    product = product_concept_factory()
    event = world_event_factory(product_concept_id=product.id)
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["rfq"],
        signal_types=["explicit_rfq"],
        forbidden_conditions=forbidden_conditions or [],
    )
    hypothesis = OpportunityCompiler(session).compile(
        CompileRequest(
            event_id=event.id,
            template_id=template.id,
            correlation_id="audit-fixture",
            numeric_assertions=numeric_assertions or [],
        )
    )[0]
    return event, hypothesis


def test_auditor_passes_current_evidence_backed_hypothesis_and_is_idempotent(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    _, hypothesis = _compile_explicit(
        session,
        product_concept_factory,
        world_event_factory,
        opportunity_template_factory,
    )
    request = AuditRequest(
        idempotency_key="audit:pass:1",
        actor="sol-auditor",
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
    )
    auditor = HypothesisAuditor(session)
    decision = auditor.audit(hypothesis.id, request)
    repeated = auditor.audit(hypothesis.id, request)

    assert decision.decision == "pass"
    assert decision.checks_json["verified_evidence"] is True
    assert decision.checks_json["feasible_route_count"] >= 1
    assert repeated.id == decision.id


def test_auditor_rejects_unsupported_numbers_expiry_and_hard_policy(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    _, hypothesis = _compile_explicit(
        session,
        product_concept_factory,
        world_event_factory,
        opportunity_template_factory,
        numeric_assertions=[{"label": "quantity", "value": 500}],
    )
    unsupported = HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="audit:unsupported-number",
            actor="sol-auditor",
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )
    prohibited = HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="audit:prohibited",
            actor="sol-auditor",
            policy_flags=["prohibited_product"],
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )
    expired = HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="audit:expired",
            actor="sol-auditor",
            as_of=datetime(2027, 1, 1, tzinfo=UTC),
        ),
    )

    assert unsupported.decision == "reject"
    assert "numeric assertions" in unsupported.reasons_json[0]
    assert prohibited.decision == "reject"
    assert any("hard policy prohibition" in reason for reason in prohibited.reasons_json)
    assert expired.decision == "reject"
    assert any("expired" in reason for reason in expired.reasons_json)


def test_auditor_returns_needs_data_when_participants_and_routes_are_unproven(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    product = product_concept_factory()
    event = world_event_factory(
        event_type="project_approval",
        subject_role="project",
        field_path="project.approval",
    )
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["project_approval"],
        signal_types=["project_approval"],
        required_claim_fields=["project.approval"],
        product_need_rules=[
            {
                "product_concept_id": product.id,
                "basis": "Project pattern suggests a possible equipment need.",
                "confidence": 0.55,
                "uncertainty": "No direct procurement evidence.",
                "applicable_event_types": ["project_approval"],
                "required_claim_fields": ["project.approval"],
            }
        ],
    )
    hypothesis = OpportunityCompiler(session).compile(
        CompileRequest(
            event_id=event.id,
            template_id=template.id,
            correlation_id="compile-needs-data",
        )
    )[0]
    decision = HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="audit:needs-data",
            actor="sol-auditor",
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )

    assert decision.decision == "needs_data"
    assert any("buyer" in reason for reason in decision.reasons_json)
    assert hypothesis.inference_assertions_json


def test_template_forbidden_condition_is_enforced_by_the_auditor(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    _, hypothesis = _compile_explicit(
        session,
        product_concept_factory,
        world_event_factory,
        opportunity_template_factory,
        forbidden_conditions=[
            {
                "field": "policy_flags",
                "operator": "contains",
                "value": "restricted_market",
                "reason": "This template prohibits the restricted market.",
            }
        ],
    )
    decision = HypothesisAuditor(session).audit(
        hypothesis.id,
        AuditRequest(
            idempotency_key="audit:template-prohibition",
            actor="sol-auditor",
            policy_flags=["restricted_market"],
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )

    assert decision.decision == "reject"
    assert decision.reasons_json == [
        "template prohibition: This template prohibits the restricted market."
    ]
