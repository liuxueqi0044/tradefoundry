from datetime import UTC, datetime, timedelta

import pytest
from bilateral_helpers import AllowPolicy, DenyPolicy, RecordingGateway, create_supplier

from tradefoundry.bilateral.contracts import (
    CandidateWhitelistRequest,
    ProductRequirement,
    RfqCreate,
    RfqFinalizeRequest,
    SendCommand,
    SupplierCandidateCreate,
)
from tradefoundry.bilateral.outbound import OutboundAuthorizationService, OutboundSendService
from tradefoundry.bilateral.rfq import RfqService
from tradefoundry.bilateral.suppliers import SupplierDiscoveryService


def _complete_rfq(route_id, product_id, session, *, key="rfq-valve", idempotency="rfq-1"):
    return RfqService(session).generate(
        route_id,
        RfqCreate(
            idempotency_key=idempotency,
            rfq_key=key,
            product_concept_id=product_id,
            destination_country="KE",
            requirement=ProductRequirement(
                specification={"material": "SS316", "diameter_mm": 50},
                packaging={"type": "export_crate"},
                certifications=["ISO 9001"],
                quantity="100",
                quantity_unit="piece",
                requested_delivery_at=datetime(2026, 10, 15, tzinfo=UTC),
                incoterm="CIF",
                payment_terms="30% deposit, 70% before shipment",
            ),
            created_by="operator",
        ),
    )


def test_rfq_generator_exposes_every_unresolved_requirement(
    session, deal_route_factory, product_concept_factory
):
    _, route = deal_route_factory()
    product = product_concept_factory(label="Pump", key="rfq-product-incomplete")
    rfq = RfqService(session).generate(
        route.id,
        RfqCreate(
            idempotency_key="rfq-incomplete-1",
            rfq_key="rfq-incomplete",
            product_concept_id=product.id,
            destination_country="NG",
            requirement=ProductRequirement(specification={"power_kw": 20}),
            created_by="operator",
        ),
    )

    assert set(rfq.unresolved_fields_json) == {
        "quantity",
        "packaging",
        "certifications",
        "requested_delivery_at",
        "incoterm",
        "payment_terms",
    }
    assert "待确认" in rfq.content_zh
    with pytest.raises(ValueError, match="unresolved"):
        RfqService(session).finalize(
            rfq.id,
            RfqFinalizeRequest(actor="reviewer", expected_content_hash=rfq.content_hash),
        )


def test_rfq_send_requires_final_whitelist_policy_and_one_time_token(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    profile, product, source_claim, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    candidate = SupplierDiscoveryService(session).add_candidate(
        route.id,
        SupplierCandidateCreate(
            idempotency_key="rfq-candidate-1",
            supplier_profile_id=profile.id,
            discovery_basis=[{"kind": "capability", "product": product.id}],
            source_claim_ids=[source_claim.id],
        ),
    )
    SupplierDiscoveryService(session, AllowPolicy()).whitelist(
        candidate.id, CandidateWhitelistRequest(requested_by="operator")
    )
    rfq = _complete_rfq(route.id, product.id, session)
    with pytest.raises(ValueError, match="final"):
        OutboundAuthorizationService(session, AllowPolicy()).authorize_rfq(
            rfq.id, profile.id, requested_by="operator"
        )
    finalized = RfqService(session).finalize(
        rfq.id, RfqFinalizeRequest(actor="reviewer", expected_content_hash=rfq.content_hash)
    )
    assert finalized.finalized_by == "reviewer"
    assert finalized.finalized_at is not None
    with pytest.raises(ValueError, match="denied"):
        OutboundAuthorizationService(session, DenyPolicy()).authorize_rfq(
            rfq.id, profile.id, requested_by="operator"
        )

    token = OutboundAuthorizationService(session, AllowPolicy()).authorize_rfq(
        rfq.id, profile.id, requested_by="operator"
    )
    gateway = RecordingGateway()
    command = SendCommand(idempotency_key="send-rfq-1", token=token.token, actor="operator")
    first = OutboundSendService(session, gateway).send(command)
    replay = OutboundSendService(session, gateway).send(command)

    assert first.id == replay.id
    assert first.resource_id == rfq.id
    assert first.resource_version == 1
    assert first.receipt_json["live_delivery"] is False
    assert len(gateway.payloads) == 1
    with pytest.raises(ValueError, match="already been consumed"):
        OutboundSendService(session, gateway).send(
            SendCommand(idempotency_key="send-rfq-2", token=token.token, actor="operator")
        )


def test_expired_approval_never_issues_send_token(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    profile, product, source_claim, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    candidate = SupplierDiscoveryService(session).add_candidate(
        route.id,
        SupplierCandidateCreate(
            idempotency_key="expired-candidate",
            supplier_profile_id=profile.id,
            discovery_basis=[{"kind": "directory"}],
            source_claim_ids=[source_claim.id],
        ),
    )
    SupplierDiscoveryService(session, AllowPolicy()).whitelist(
        candidate.id, CandidateWhitelistRequest(requested_by="operator")
    )
    rfq = _complete_rfq(route.id, product.id, session, key="rfq-expired", idempotency="rfq-expired")
    RfqService(session).finalize(
        rfq.id, RfqFinalizeRequest(actor="reviewer", expected_content_hash=rfq.content_hash)
    )
    expired_policy = AllowPolicy(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(ValueError, match="expired"):
        OutboundAuthorizationService(session, expired_policy).authorize_rfq(
            rfq.id, profile.id, requested_by="operator"
        )


def test_supplier_removed_from_whitelist_after_authorization_still_cannot_send(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    profile, product, source_claim, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    candidate = SupplierDiscoveryService(session).add_candidate(
        route.id,
        SupplierCandidateCreate(
            idempotency_key="revoked-candidate",
            supplier_profile_id=profile.id,
            discovery_basis=[{"kind": "directory"}],
            source_claim_ids=[source_claim.id],
        ),
    )
    SupplierDiscoveryService(session, AllowPolicy()).whitelist(
        candidate.id, CandidateWhitelistRequest(requested_by="operator")
    )
    rfq = _complete_rfq(route.id, product.id, session, key="rfq-revoked", idempotency="rfq-revoked")
    RfqService(session).finalize(
        rfq.id, RfqFinalizeRequest(actor="reviewer", expected_content_hash=rfq.content_hash)
    )
    token = OutboundAuthorizationService(session, AllowPolicy()).authorize_rfq(
        rfq.id, profile.id, requested_by="operator"
    )
    candidate.status = "candidate"
    session.commit()

    with pytest.raises(ValueError, match="no longer whitelisted"):
        OutboundSendService(session, RecordingGateway()).send(
            SendCommand(idempotency_key="revoked-send", token=token.token, actor="operator")
        )
