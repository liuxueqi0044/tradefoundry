from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradefoundry.controltower.contracts import (
    ApprovalDecisionCreate,
    ApprovalRequestCreate,
    Decision,
    PolicyBundleCreate,
    PolicyCondition,
    PolicyDecisionCreate,
    PolicyRule,
)
from tradefoundry.controltower.governance import ApprovalService
from tradefoundry.controltower.policy import PolicyBundleService, PolicyEngine
from tradefoundry.ingestion.hashing import payload_hash

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def activate_policy_bundle(session, *, key="tradefoundry-actions", rules=None, suffix="1"):
    rules = rules or [
        PolicyRule(
            rule_key="first-contact-needs-compliance",
            priority=50,
            actions=["first_buyer_contact"],
            effect=Decision.REQUIRE_APPROVAL,
            conditions=[],
            reasons=["First buyer contact requires compliance approval."],
            obligations={
                "approval_chain": [{"role": "compliance", "approvals": 1}],
                "separation_of_duties": True,
            },
        ),
        PolicyRule(
            rule_key="default-reviewed-allow",
            priority=1,
            actions=["supplier_rfq", "communication_eligibility"],
            effect=Decision.ALLOW,
            conditions=[],
            reasons=["Reviewed low-risk rule allows the action."],
        ),
    ]
    bundle = PolicyBundleService(session).create(
        PolicyBundleCreate(
            bundle_key=key,
            idempotency_key=f"bundle-{key}-{suffix}",
            rules=rules,
            created_by="sol-architect",
        )
    )
    return PolicyBundleService(session).activate(bundle.id)


def approved_action(
    session,
    *,
    action="first_buyer_contact",
    resource_type="message_draft",
    resource_id="resource-1",
    params=None,
    subject_refs=None,
    suffix="1",
    rules=None,
):
    activate_policy_bundle(session, rules=rules, suffix=suffix)
    params = params or {
        "recipient_ref": "contact-1",
        "payload_hash": "a" * 64,
        "resource_version": 1,
        "actor": "operator-1",
    }
    policy = PolicyEngine(session).decide(
        PolicyDecisionCreate(
            bundle_key="tradefoundry-actions",
            idempotency_key=f"decision-{suffix}",
            actor="operator-1",
            actor_roles=["sales"],
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            context={"params_hash": payload_hash(params), "risk": "reviewed"},
        )
    )
    approval = ApprovalService(session).create(
        ApprovalRequestCreate(
            policy_decision_id=policy.id,
            idempotency_key=f"approval-{suffix}",
            requester="operator-1",
            params=params,
            subject_refs=subject_refs or ["entity:buyer-1"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    approval = ApprovalService(session).decide(
        approval.id,
        ApprovalDecisionCreate(
            idempotency_key=f"approval-decision-{suffix}",
            approver="compliance-1",
            approver_roles=["compliance"],
            decision="approve",
            reason="Reviewed identity, purpose and supporting evidence.",
        ),
    )
    return policy, approval, params


def communication_rules():
    return [
        PolicyRule(
            rule_key="deny-suppressed",
            priority=100,
            actions=["communicate"],
            effect=Decision.DENY,
            conditions=[PolicyCondition(path="context.suppressed", operator="eq", value=True)],
            reasons=["Contact is suppressed."],
        ),
        PolicyRule(
            rule_key="deny-incomplete-context",
            priority=90,
            actions=["communicate"],
            effect=Decision.DENY,
            conditions=[
                PolicyCondition(path="context.contact_point_present", operator="eq", value=False)
            ],
            reasons=["No active contact point exists."],
        ),
        PolicyRule(
            rule_key="deny-expired-retention",
            priority=90,
            actions=["communicate"],
            effect=Decision.DENY,
            conditions=[
                PolicyCondition(path="context.retention_expired", operator="eq", value=True)
            ],
            reasons=["Retention period expired."],
        ),
        PolicyRule(
            rule_key="deny-context-mismatch",
            priority=90,
            actions=["communicate"],
            effect=Decision.DENY,
            conditions=[
                PolicyCondition(path="context.lawful_basis_mismatch", operator="eq", value=True)
            ],
            reasons=["Declared lawful basis differs from the evidence-backed contact point."],
        ),
        PolicyRule(
            rule_key="deny-jurisdiction-mismatch",
            priority=90,
            actions=["communicate"],
            effect=Decision.DENY,
            conditions=[
                PolicyCondition(path="context.jurisdiction_matches", operator="eq", value=False)
            ],
            reasons=["Contact-point jurisdiction does not match the requested jurisdiction."],
        ),
        PolicyRule(
            rule_key="first-contact-approval",
            priority=50,
            actions=["communicate"],
            effect=Decision.REQUIRE_APPROVAL,
            conditions=[PolicyCondition(path="context.first_contact", operator="eq", value=True)],
            reasons=["First contact requires approval."],
            obligations={
                "approval_chain": [{"role": "compliance", "approvals": 1}],
                "separation_of_duties": True,
            },
        ),
        PolicyRule(
            rule_key="allow-reviewed-followup",
            priority=10,
            actions=["communicate"],
            effect=Decision.ALLOW,
            conditions=[
                PolicyCondition(path="context.lawful_basis_present", operator="eq", value=True)
            ],
            reasons=["Reviewed lawful basis permits follow-up."],
        ),
    ]
