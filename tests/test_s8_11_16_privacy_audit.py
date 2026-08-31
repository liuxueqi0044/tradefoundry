from datetime import UTC, datetime, timedelta

from bilateral_helpers import DenyPolicy, create_buyer_contact
from control_helpers import activate_policy_bundle, approved_action, communication_rules

from tradefoundry.bilateral.contracts import SuppressionCreate
from tradefoundry.bilateral.crm import CommunicationEligibilityService
from tradefoundry.controltower.audit import AuditExportService
from tradefoundry.controltower.contracts import (
    AuditExportCreate,
    CommunicationEvaluate,
    ExecutionTokenIssue,
    RiskCaseOpen,
)
from tradefoundry.controltower.governance import ExecutionTokenService, FreezeService
from tradefoundry.controltower.privacy import CommunicationPolicyService

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _communication_request(contact_id, *, key, first=True, **updates):
    values = {
        "idempotency_key": key,
        "contact_id": contact_id,
        "bundle_key": "communications",
        "actor": "sales-operator",
        "actor_roles": ["sales"],
        "channel": "email",
        "jurisdiction": "KE",
        "purpose": "first_contact" if first else "reply",
        "lawful_basis": "legitimate_interest_reviewed",
        "retention_deadline": NOW + timedelta(days=90),
        "first_contact": first,
        "as_of": NOW,
    }
    values.update(updates)
    return CommunicationEvaluate(**values)


def test_communication_policy_centralizes_first_contact_followup_and_suppression(
    session, master_entity_factory, master_claim_factory
):
    activate_policy_bundle(
        session, key="communications", rules=communication_rules(), suffix="privacy"
    )
    _, contact, _, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory, index=81
    )
    first = CommunicationPolicyService(session).evaluate(
        _communication_request(contact.id, key="communication-first")
    )
    assert first.decision == "require_approval"
    followup = CommunicationPolicyService(session).evaluate(
        _communication_request(contact.id, key="communication-followup", first=False)
    )
    assert followup.decision == "allow"
    CommunicationEligibilityService(session, DenyPolicy()).suppress(
        contact.id,
        SuppressionCreate(
            idempotency_key="privacy-suppression",
            channel="email",
            reason="unsubscribe",
            source_ref="reply:unsubscribe",
            occurred_at=NOW,
        ),
    )
    suppressed = CommunicationPolicyService(session).evaluate(
        _communication_request(contact.id, key="communication-suppressed", first=False)
    )
    assert suppressed.decision == "deny"
    assert suppressed.suppression_ids_json


def test_communication_policy_denies_retention_basis_and_jurisdiction_mismatches(
    session, master_entity_factory, master_claim_factory
):
    activate_policy_bundle(
        session, key="communications", rules=communication_rules(), suffix="mismatch"
    )
    _, contact, _, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory, index=82
    )
    expired = CommunicationPolicyService(session).evaluate(
        _communication_request(
            contact.id,
            key="communication-expired",
            first=False,
            retention_deadline=NOW - timedelta(seconds=1),
        )
    )
    assert expired.decision == "deny"
    basis = CommunicationPolicyService(session).evaluate(
        _communication_request(
            contact.id,
            key="communication-basis-mismatch",
            first=False,
            lawful_basis="consent",
        )
    )
    assert basis.decision == "deny"
    jurisdiction = CommunicationPolicyService(session).evaluate(
        _communication_request(
            contact.id,
            key="communication-jurisdiction-mismatch",
            first=False,
            jurisdiction="US",
        )
    )
    assert jurisdiction.decision == "deny"


def test_audit_export_links_policy_approval_token_freeze_and_evidence_with_redaction(
    session, master_claim_factory
):
    policy, approval, params = approved_action(session, suffix="audit")
    token = ExecutionTokenService(session).issue(
        ExecutionTokenIssue(
            approval_request_id=approval.id,
            params=params,
            issued_by="control-tower",
        )
    )
    evidence = master_claim_factory(
        value={"registry_id": "sensitive-registry-value"},
        field_path="compliance.identity_resolution",
        verified=True,
    )
    FreezeService(session).open_case(
        RiskCaseOpen(
            case_key="audit-risk-case",
            idempotency_key="audit-risk-case",
            case_type="manual_anomaly",
            severity="high",
            source_reference="resource-1",
            subject_refs=["entity:buyer-1"],
            reason="Manual evidence-backed anomaly review.",
            evidence_claim_ids=[evidence.id],
            opened_by="risk-worker",
        )
    )
    operational = AuditExportService(session).export(
        AuditExportCreate(
            idempotency_key="audit-operational",
            resource_refs=["resource-1", "entity:buyer-1"],
            requested_by="sales-manager",
            requester_role="sales",
        )
    )
    records = operational.package_json["records"]
    assert records["policy_decisions"][0]["action"] == "first_buyer_contact"
    assert records["approval_requests"][0]["status"] == "approved"
    assert records["execution_tokens"][0]["id"] == token.token_id
    assert "token_hash" not in records["execution_tokens"][0]
    assert records["execution_tokens"][0]["params_json"]["redacted"] is True
    assert records["evidence_claims"][0]["value_json"]["redacted"] is True
    full = AuditExportService(session).export(
        AuditExportCreate(
            idempotency_key="audit-full",
            resource_refs=["resource-1", "entity:buyer-1"],
            requested_by="auditor-1",
            requester_role="compliance_auditor",
        )
    )
    assert full.redaction_profile == "auditor_full"
    assert full.package_json["records"]["evidence_claims"][0]["value_json"] == {
        "registry_id": "sensitive-registry-value"
    }
    assert full.package_hash != operational.package_hash
    assert policy.id == records["policy_decisions"][0]["id"]
