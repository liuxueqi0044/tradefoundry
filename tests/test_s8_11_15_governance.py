from datetime import UTC, datetime, timedelta

import httpx
import pytest
from control_helpers import activate_policy_bundle, approved_action

from tradefoundry.controltower.contracts import (
    ApprovalDecisionCreate,
    ApprovalRequestCreate,
    Decision,
    ExecutionConsumption,
    ExecutionReservation,
    ExecutionTokenIssue,
    PolicyBundleCreate,
    PolicyCondition,
    PolicyDecisionCreate,
    PolicyRule,
    RiskCaseOpen,
)
from tradefoundry.controltower.governance import (
    ApprovalService,
    ExecutionTokenService,
    FreezeService,
)
from tradefoundry.controltower.policy import (
    OpaPolicyEvaluator,
    PolicyBundleService,
    PolicyEngine,
)
from tradefoundry.ingestion.hashing import payload_hash


def test_policy_engine_is_versioned_deterministic_and_default_deny(session):
    bundle = activate_policy_bundle(
        session,
        key="deterministic",
        rules=[
            PolicyRule(
                rule_key="allow-sales",
                priority=20,
                actions=["quote"],
                effect=Decision.ALLOW,
                conditions=[
                    PolicyCondition(path="actor.roles", operator="contains", value="sales")
                ],
                reasons=["Sales role can quote."],
            ),
            PolicyRule(
                rule_key="deny-frozen",
                priority=100,
                actions=["quote"],
                effect=Decision.DENY,
                conditions=[PolicyCondition(path="context.frozen", operator="eq", value=True)],
                reasons=["Frozen resources cannot be quoted."],
            ),
        ],
    )
    assert bundle.version_no == 1
    engine = PolicyEngine(session)
    denied = engine.decide(
        PolicyDecisionCreate(
            bundle_key="deterministic",
            idempotency_key="policy-frozen",
            actor="sales-1",
            actor_roles=["sales"],
            action="quote",
            resource_type="route",
            resource_id="route-1",
            context={"frozen": True},
        )
    )
    assert denied.decision == "deny"
    assert denied.matched_rule_key == "deny-frozen"
    replay = engine.decide(
        PolicyDecisionCreate(
            bundle_key="deterministic",
            idempotency_key="policy-frozen",
            actor="sales-1",
            actor_roles=["sales"],
            action="quote",
            resource_type="route",
            resource_id="route-1",
            context={"frozen": True},
        )
    )
    assert replay.id == denied.id
    default_deny = engine.decide(
        PolicyDecisionCreate(
            bundle_key="deterministic",
            idempotency_key="policy-unmatched",
            actor="viewer-1",
            action="delete_everything",
            resource_type="route",
            resource_id="route-1",
        )
    )
    assert default_deny.decision == "deny"
    assert default_deny.matched_rule_key is None


def test_opa_adapter_preserves_decision_id_and_external_revision(session):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/tradefoundry/decision"
        return httpx.Response(
            200,
            json={
                "decision_id": "opa-decision-1",
                "result": {
                    "decision": "require_approval",
                    "reasons": ["OPA reviewed rule matched."],
                    "obligations": {"approval_chain": [{"role": "compliance", "approvals": 1}]},
                    "matched_rule_key": "opa-high-risk",
                    "revision": "bundle-revision-42",
                },
            },
        )

    bundle = PolicyBundleService(session).create(
        PolicyBundleCreate(
            bundle_key="opa-actions",
            idempotency_key="opa-bundle",
            backend="opa",
            rules=[
                PolicyRule(
                    rule_key="external-placeholder",
                    actions=["*"],
                    effect=Decision.DENY,
                    reasons=["Evaluated externally."],
                )
            ],
            created_by="sol",
        )
    )
    PolicyBundleService(session).activate(bundle.id)
    evaluator = OpaPolicyEvaluator(
        "https://opa.invalid",
        "tradefoundry/decision",
        transport=httpx.MockTransport(handler),
    )
    result = PolicyEngine(session, external_evaluators={"opa-actions": evaluator}).decide(
        PolicyDecisionCreate(
            bundle_key="opa-actions",
            idempotency_key="opa-evaluate",
            actor="operator",
            action="payment",
            resource_type="deal",
            resource_id="deal-1",
        )
    )
    assert result.decision == "require_approval"
    assert result.backend_decision_id == "opa-decision-1"
    assert result.policy_version == "bundle-revision-42"


def test_approval_rejects_parameter_tampering_and_self_approval(session):
    params = {"amount": "1000.0000", "currency": "USD"}
    rules = [
        PolicyRule(
            rule_key="payment-approval",
            actions=["payment"],
            effect=Decision.REQUIRE_APPROVAL,
            reasons=["Payment requires approval."],
            obligations={
                "approval_chain": [{"role": "finance", "approvals": 1}],
                "separation_of_duties": True,
            },
        )
    ]
    activate_policy_bundle(session, key="payments", rules=rules)
    policy = PolicyEngine(session).decide(
        PolicyDecisionCreate(
            bundle_key="payments",
            idempotency_key="payment-policy",
            actor="requester",
            action="payment",
            resource_type="invoice",
            resource_id="invoice-1",
            context={"params_hash": payload_hash(params)},
        )
    )
    with pytest.raises(ValueError, match="do not match"):
        ApprovalService(session).create(
            ApprovalRequestCreate(
                policy_decision_id=policy.id,
                idempotency_key="tampered-approval",
                requester="requester",
                params={"amount": "2000.0000", "currency": "USD"},
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    approval = ApprovalService(session).create(
        ApprovalRequestCreate(
            policy_decision_id=policy.id,
            idempotency_key="valid-approval",
            requester="requester",
            params=params,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    with pytest.raises(ValueError, match="own restricted action"):
        ApprovalService(session).decide(
            approval.id,
            ApprovalDecisionCreate(
                idempotency_key="self-approval",
                approver="requester",
                approver_roles=["finance"],
                decision="approve",
                reason="Attempted self approval is prohibited.",
            ),
        )


def test_tiered_and_dual_approval_chain_advances_in_order(session):
    rules = [
        PolicyRule(
            rule_key="critical-action",
            actions=["critical_action"],
            effect=Decision.REQUIRE_APPROVAL,
            reasons=["Critical action requires dual compliance and finance approval."],
            obligations={
                "approval_chain": [
                    {"role": "compliance", "approvals": 2},
                    {"role": "finance", "approvals": 1},
                ],
                "separation_of_duties": True,
            },
        )
    ]
    params = {"scope": "critical"}
    activate_policy_bundle(session, key="critical", rules=rules)
    policy = PolicyEngine(session).decide(
        PolicyDecisionCreate(
            bundle_key="critical",
            idempotency_key="critical-policy",
            actor="operator",
            action="critical_action",
            resource_type="resource",
            resource_id="resource-1",
            context={"params_hash": payload_hash(params)},
        )
    )
    approval = ApprovalService(session).create(
        ApprovalRequestCreate(
            policy_decision_id=policy.id,
            idempotency_key="critical-approval",
            requester="operator",
            params=params,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    for index in (1, 2):
        approval = ApprovalService(session).decide(
            approval.id,
            ApprovalDecisionCreate(
                idempotency_key=f"compliance-{index}",
                approver=f"compliance-{index}",
                approver_roles=["compliance"],
                decision="approve",
                reason="Independent compliance review completed.",
            ),
        )
    assert approval.status == "pending"
    assert ApprovalService(session).steps(approval.id)[1].status == "pending"
    approval = ApprovalService(session).decide(
        approval.id,
        ApprovalDecisionCreate(
            idempotency_key="finance-final",
            approver="finance-1",
            approver_roles=["finance"],
            decision="approve",
            reason="Finance reviewed the final exposure.",
        ),
    )
    assert approval.status == "approved"


def test_execution_token_is_single_issue_bound_reserved_and_single_use(session):
    _, approval, params = approved_action(session)
    service = ExecutionTokenService(session)
    issued = service.issue(
        ExecutionTokenIssue(
            approval_request_id=approval.id,
            params=params,
            issued_by="control-tower",
        )
    )
    with pytest.raises(ValueError, match="already issued"):
        service.issue(
            ExecutionTokenIssue(
                approval_request_id=approval.id,
                params=params,
                issued_by="control-tower",
            )
        )
    with pytest.raises(ValueError, match="not bound"):
        service.reserve(
            ExecutionReservation(
                token=issued.token,
                action="first_buyer_contact",
                resource_type="message_draft",
                resource_id="resource-1",
                params={**params, "payload_hash": "b" * 64},
                effect_key="effect-tampered",
            )
        )
    reservation = ExecutionReservation(
        token=issued.token,
        action="first_buyer_contact",
        resource_type="message_draft",
        resource_id="resource-1",
        params=params,
        effect_key="effect-1",
    )
    assert service.reserve(reservation).state == "reserved"
    assert service.reserve(reservation).reservation_effect_key == "effect-1"
    with pytest.raises(ValueError, match="different effect"):
        service.reserve(reservation.model_copy(update={"effect_key": "effect-2"}))
    consumption = ExecutionConsumption(
        token=issued.token,
        effect_key="effect-1",
        execution_reference="provider-message-1",
    )
    assert service.consume(consumption).state == "consumed"
    assert service.consume(consumption).execution_reference == "provider-message-1"
    with pytest.raises(ValueError, match="already been consumed"):
        service.inspect(issued.token)


def test_freeze_created_after_token_issue_still_blocks_execution(session):
    _, approval, params = approved_action(session, suffix="freeze-after-issue")
    service = ExecutionTokenService(session)
    issued = service.issue(
        ExecutionTokenIssue(
            approval_request_id=approval.id,
            params=params,
            issued_by="control-tower",
        )
    )
    FreezeService(session).open_case(
        RiskCaseOpen(
            case_key="late-risk-case",
            idempotency_key="late-risk-case",
            case_type="sanctions_screening",
            severity="high",
            source_reference="screening-late",
            subject_refs=["entity:buyer-1"],
            reason="A possible sanctions match appeared after approval.",
            opened_by="screening-worker",
        )
    )
    with pytest.raises(ValueError, match="active freeze"):
        service.inspect(issued.token)
