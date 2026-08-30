from decimal import Decimal

import pytest
from bilateral_helpers import AllowPolicy, DenyPolicy, create_supplier

from tradefoundry.bilateral.contracts import (
    CandidateWhitelistRequest,
    SupplierCandidateCreate,
)
from tradefoundry.bilateral.suppliers import SupplierDiscoveryService, SupplierMasterService


def test_supplier_master_keeps_kind_multisource_evidence_and_capability(
    session, master_entity_factory, master_claim_factory, product_concept_factory
):
    profile, product, identity_claim, capability_claim = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )

    bundle = SupplierMasterService(session).get(profile.id)

    assert bundle.profile.supplier_kind == "factory"
    assert {item["source_claim_id"] for item in bundle.evidence} == {
        identity_claim.id,
        capability_claim.id,
    }
    assert bundle.capabilities[0]["product_concept_id"] == product.id
    assert bundle.capabilities[0]["certifications"] == ["ISO 9001"]


def test_candidate_platform_price_is_never_promoted_to_quote(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    profile, _, source_claim, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    candidate = SupplierDiscoveryService(session).add_candidate(
        route.id,
        SupplierCandidateCreate(
            idempotency_key="candidate-platform-1",
            supplier_profile_id=profile.id,
            discovery_basis=[{"kind": "industrial_cluster", "value": "Wenzhou"}],
            source_claim_ids=[source_claim.id],
            missing_fields=["audited_capacity"],
            displayed_price={"amount": str(Decimal("2.99")), "currency": "USD"},
        ),
    )

    assert candidate.displayed_price_json["amount"] == "2.99"
    assert candidate.displayed_price_is_quote is False
    assert candidate.missing_fields_json == ["audited_capacity"]


def test_supplier_whitelist_requires_external_policy_allow(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    profile, _, source_claim, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    candidate = SupplierDiscoveryService(session).add_candidate(
        route.id,
        SupplierCandidateCreate(
            idempotency_key="candidate-whitelist-1",
            supplier_profile_id=profile.id,
            discovery_basis=[{"kind": "directory", "value": "verified directory"}],
            source_claim_ids=[source_claim.id],
        ),
    )
    with pytest.raises(ValueError, match="approved allow"):
        SupplierDiscoveryService(session, DenyPolicy()).whitelist(
            candidate.id, CandidateWhitelistRequest(requested_by="operator")
        )

    whitelisted = SupplierDiscoveryService(session, AllowPolicy()).whitelist(
        candidate.id, CandidateWhitelistRequest(requested_by="operator")
    )
    assert whitelisted.status == "whitelisted"
    assert whitelisted.whitelist_policy_ref == "policy:supplier_whitelist:approved"
    assert whitelisted.whitelisted_by == "human-approver"
