from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradefoundry.bilateral.contracts import (
    AuthorizationContext,
    BuyerProfileCreate,
    ContactAffiliationInput,
    ContactCreate,
    ContactPointInput,
    CostScenario,
    EligibilityRequest,
    PolicyAuthorization,
    SupplierCapabilityInput,
    SupplierEvidenceInput,
    SupplierProfileCreate,
)
from tradefoundry.bilateral.crm import BuyerCrmService
from tradefoundry.bilateral.ports import OutboundPayload, OutboundReceipt
from tradefoundry.bilateral.suppliers import SupplierMasterService


class AllowPolicy:
    def __init__(self, *, expires_at: datetime | None = None):
        self.expires_at = expires_at
        self.authorization_calls: list[AuthorizationContext] = []
        self.eligibility_calls: list[tuple[str, EligibilityRequest]] = []

    def authorize(self, context: AuthorizationContext) -> PolicyAuthorization:
        self.authorization_calls.append(context)
        return PolicyAuthorization(
            decision="allow",
            policy_decision_ref=f"policy:{context.action_kind}:approved",
            policy_version="fixture-policy-v1",
            approved_by="human-approver",
            expires_at=self.expires_at
            or datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1),
        )

    def communication_eligibility(
        self, *, contact_id: str, request: EligibilityRequest
    ) -> PolicyAuthorization:
        self.eligibility_calls.append((contact_id, request))
        return PolicyAuthorization(
            decision="allow",
            policy_decision_ref="policy:communication:allow",
            policy_version="fixture-policy-v1",
            approved_by="policy-engine",
        )


class DenyPolicy(AllowPolicy):
    def authorize(self, context: AuthorizationContext) -> PolicyAuthorization:
        return PolicyAuthorization(
            decision="deny",
            policy_decision_ref="policy:deny",
            policy_version="fixture-policy-v1",
            reasons=["denied by fixture policy"],
        )

    def communication_eligibility(
        self, *, contact_id: str, request: EligibilityRequest
    ) -> PolicyAuthorization:
        return PolicyAuthorization(
            decision="deny",
            policy_decision_ref="policy:communication:deny",
            policy_version="fixture-policy-v1",
            reasons=["jurisdiction rule denied communication"],
        )


class RecordingGateway:
    name = "recording-sandbox"

    def __init__(self):
        self.effects: dict[str, OutboundReceipt] = {}
        self.payloads: list[OutboundPayload] = []

    def send(self, payload: OutboundPayload, *, effect_key: str) -> OutboundReceipt:
        if effect_key in self.effects:
            return self.effects[effect_key]
        self.payloads.append(payload)
        receipt = OutboundReceipt(
            gateway_name=self.name,
            external_message_id=f"sandbox-{len(self.payloads)}",
            status="recorded",
            details={"effect_key": effect_key, "live_delivery": False},
        )
        self.effects[effect_key] = receipt
        return receipt


class StaticCostScenarios:
    def __init__(self, scenario: CostScenario | None = None):
        self.scenario = scenario or CostScenario(
            reference="cost:scenario:1",
            snapshot_hash="a" * 64,
            calculator_version="board8-fixture-v1",
            status="estimated",
            total_cost=Decimal("800.00"),
            currency="USD",
            quantity=Decimal("100"),
            quantity_unit="piece",
            assumptions=["Freight is estimated."],
        )

    def get(self, reference: str) -> CostScenario:
        if reference != self.scenario.reference:
            raise LookupError(reference)
        return self.scenario


def create_supplier(
    session,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
    *,
    index: int = 1,
    kind: str = "factory",
):
    entity = master_entity_factory(
        name=f"Supplier {index}", entity_type="organization", key=f"supplier-entity-{index}"
    )
    identity_claim = master_claim_factory(
        value=f"Supplier {index} is a {kind}", field_path="supplier.kind", verified=True
    )
    capability_claim = master_claim_factory(
        value=f"Supplier {index} makes valves", field_path="supplier.capability", verified=True
    )
    product = product_concept_factory(
        label=f"Industrial Valve {index}", key=f"supplier-product-{index}"
    )
    profile = SupplierMasterService(session).create(
        SupplierProfileCreate(
            idempotency_key=f"supplier-profile-{index}",
            entity_id=entity.id,
            supplier_kind=kind,
            review_status="verified",
            attributes={"industrial_cluster": "Wenzhou"},
            evidence=[
                SupplierEvidenceInput(
                    field_path="supplier.kind",
                    value=kind,
                    source_claim_id=identity_claim.id,
                    review_status="verified",
                ),
                SupplierEvidenceInput(
                    field_path="supplier.location",
                    value="Wenzhou",
                    source_claim_id=capability_claim.id,
                    review_status="verified",
                ),
            ],
            capabilities=[
                SupplierCapabilityInput(
                    product_concept_id=product.id,
                    source_claim_id=capability_claim.id,
                    specifications={"material": "SS316", "diameter_mm": 50},
                    certifications=["ISO 9001"],
                    capacity={"monthly": 5000, "unit": "piece"},
                    review_status="verified",
                )
            ],
        )
    )
    return profile, product, identity_claim, capability_claim


def create_buyer_contact(
    session,
    master_entity_factory,
    master_claim_factory,
    *,
    index: int = 1,
):
    entity = master_entity_factory(
        name=f"Buyer {index}", entity_type="organization", key=f"buyer-entity-{index}"
    )
    buyer_claim = master_claim_factory(
        value=f"Buyer {index} issued a valve tender",
        field_path="buyer.procurement_context",
        verified=True,
    )
    role_claim = master_claim_factory(
        value=f"Procurement manager at Buyer {index}",
        field_path="contact.role",
        verified=True,
    )
    buyer = BuyerCrmService(session).create_buyer(
        BuyerProfileCreate(
            idempotency_key=f"buyer-profile-{index}",
            entity_id=entity.id,
            attributes={"market": "Kenya"},
            evidence_claim_ids=[buyer_claim.id],
            review_status="verified",
        )
    )
    contact = BuyerCrmService(session).create_contact(
        ContactCreate(
            idempotency_key=f"buyer-contact-{index}",
            contact_key=f"contact-{index}",
            display_name=f"Buyer Contact {index}",
            contact_points=[
                ContactPointInput(
                    channel="email",
                    value=f"Buyer{index}@Example.com",
                    source_claim_id=role_claim.id,
                    lawful_basis="legitimate_interest_reviewed",
                    jurisdiction="KE",
                    captured_at=datetime(2026, 8, 30, tzinfo=UTC),
                )
            ],
            affiliations=[
                ContactAffiliationInput(
                    buyer_profile_id=buyer.id,
                    role="procurement_manager",
                    source_claim_id=role_claim.id,
                    valid_from=datetime(2025, 1, 1, tzinfo=UTC),
                ),
                ContactAffiliationInput(
                    buyer_profile_id=buyer.id,
                    role="technical_evaluator",
                    source_claim_id=role_claim.id,
                    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ],
        )
    )
    return buyer, contact, buyer_claim, role_claim
