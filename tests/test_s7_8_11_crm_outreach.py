from datetime import UTC, datetime

import pytest
from bilateral_helpers import (
    AllowPolicy,
    RecordingGateway,
    create_buyer_contact,
    create_supplier,
)

from tradefoundry.bilateral.contracts import (
    EligibilityRequest,
    GroundedContextItem,
    MessageDraftCreate,
    SendCommand,
    SuppressionCreate,
)
from tradefoundry.bilateral.crm import BuyerCrmService, CommunicationEligibilityService
from tradefoundry.bilateral.messaging import MessageDraftService
from tradefoundry.bilateral.outbound import OutboundAuthorizationService, OutboundSendService


def _eligibility(session, contact_id, policy, *, key="eligibility-1"):
    return CommunicationEligibilityService(session, policy).evaluate(
        contact_id,
        EligibilityRequest(
            idempotency_key=key,
            channel="email",
            jurisdiction="KE",
            purpose="first_contact",
            evaluated_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )


def test_contact_keeps_multiple_roles_history_source_and_lawful_basis(
    session, master_entity_factory, master_claim_factory
):
    _, contact, _, role_claim = create_buyer_contact(
        session, master_entity_factory, master_claim_factory
    )

    bundle = BuyerCrmService(session).get_contact(contact.id)

    assert {item["role"] for item in bundle.affiliations} == {
        "procurement_manager",
        "technical_evaluator",
    }
    assert {item["source_claim_id"] for item in bundle.affiliations} == {role_claim.id}
    assert bundle.contact_points[0]["normalized_value"] == "buyer1@example.com"
    assert bundle.contact_points[0]["lawful_basis"] == "legitimate_interest_reviewed"


def test_unsubscribe_precedes_policy_and_forces_deny(
    session, master_entity_factory, master_claim_factory
):
    _, contact, _, _ = create_buyer_contact(session, master_entity_factory, master_claim_factory)
    policy = AllowPolicy()
    CommunicationEligibilityService(session, policy).suppress(
        contact.id,
        SuppressionCreate(
            idempotency_key="unsubscribe-1",
            channel="all",
            reason="unsubscribe",
            source_ref="email-unsubscribe:message-1",
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )
    decision = _eligibility(session, contact.id, policy)

    assert decision.decision == "deny"
    assert decision.blockers_json[0].startswith("suppression:unsubscribe")
    assert policy.eligibility_calls == []


def test_grounded_message_flags_unsupported_commercial_assertion(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    buyer, contact, buyer_claim, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory
    )
    _, _, _, capability_claim = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    eligibility = _eligibility(session, contact.id, AllowPolicy())
    draft = MessageDraftService(session).create(
        route.id,
        MessageDraftCreate(
            idempotency_key="draft-unsupported-1",
            draft_key="first-contact",
            buyer_profile_id=buyer.id,
            contact_id=contact.id,
            eligibility_decision_id=eligibility.id,
            buyer_context=[
                GroundedContextItem(text="Buyer 1 issued a valve tender", claim_id=buyer_claim.id)
            ],
            capability_context=[
                GroundedContextItem(text="Supplier 1 makes valves", claim_id=capability_claim.id)
            ],
            desired_next_step="确认技术规格",
            assertions={"price": "USD 1 delivered"},
            created_by="operator",
        ),
    )

    assert draft.prohibited_findings_json == ["unsupported_price:USD 1 delivered"]
    assert any("certification" in item for item in draft.required_confirmations_json)
    with pytest.raises(ValueError, match="prohibited"):
        OutboundAuthorizationService(session, AllowPolicy()).authorize_first_contact(
            draft.id, requested_by="operator"
        )


def test_message_context_text_cannot_claim_more_than_its_evidence(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    buyer, contact, buyer_claim, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory
    )
    _, _, _, capability_claim = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    eligibility = _eligibility(session, contact.id, AllowPolicy(), key="eligibility-grounding")

    with pytest.raises(ValueError, match="not grounded"):
        MessageDraftService(session).create(
            route.id,
            MessageDraftCreate(
                idempotency_key="draft-fabricated-context",
                draft_key="fabricated-context",
                buyer_profile_id=buyer.id,
                contact_id=contact.id,
                eligibility_decision_id=eligibility.id,
                buyer_context=[
                    GroundedContextItem(
                        text="Buyer 1 guarantees a million-dollar order", claim_id=buyer_claim.id
                    )
                ],
                capability_context=[
                    GroundedContextItem(
                        text="Supplier 1 makes valves", claim_id=capability_claim.id
                    )
                ],
                desired_next_step="确认需求",
                created_by="operator",
            ),
        )


def test_first_contact_needs_fresh_human_token_and_late_suppression_still_blocks_send(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    buyer, contact, buyer_claim, _ = create_buyer_contact(
        session, master_entity_factory, master_claim_factory
    )
    _, _, _, capability_claim = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    eligibility = _eligibility(session, contact.id, AllowPolicy(), key="eligibility-send")
    draft = MessageDraftService(session).create(
        route.id,
        MessageDraftCreate(
            idempotency_key="draft-send-1",
            draft_key="first-contact-send",
            buyer_profile_id=buyer.id,
            contact_id=contact.id,
            eligibility_decision_id=eligibility.id,
            buyer_context=[
                GroundedContextItem(text="Buyer 1 issued a valve tender", claim_id=buyer_claim.id)
            ],
            capability_context=[
                GroundedContextItem(text="Supplier 1 makes valves", claim_id=capability_claim.id)
            ],
            desired_next_step="安排一次 20 分钟规格确认会议",
            created_by="operator",
        ),
    )
    token = OutboundAuthorizationService(session, AllowPolicy()).authorize_first_contact(
        draft.id, requested_by="operator"
    )
    CommunicationEligibilityService(session, AllowPolicy()).suppress(
        contact.id,
        SuppressionCreate(
            idempotency_key="late-complaint",
            channel="email",
            reason="complaint",
            source_ref="complaint:case-1",
            occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        ),
    )
    gateway = RecordingGateway()
    with pytest.raises(ValueError, match="became suppressed"):
        OutboundSendService(session, gateway).send(
            SendCommand(idempotency_key="blocked-late-send", token=token.token, actor="operator")
        )
    assert gateway.payloads == []
