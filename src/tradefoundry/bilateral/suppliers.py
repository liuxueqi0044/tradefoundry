from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    aware,
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import (
    AuthorizationContext,
    CandidateWhitelistRequest,
    PerformanceEventCreate,
    PerformanceSnapshotRequest,
    SupplierCandidateCreate,
    SupplierProfileBundle,
    SupplierProfileCreate,
)
from tradefoundry.bilateral.models import (
    SupplierCandidateRow,
    SupplierCapabilityRow,
    SupplierPerformanceEventRow,
    SupplierPerformanceSnapshotRow,
    SupplierProfileEvidenceRow,
    SupplierProfileRow,
)
from tradefoundry.bilateral.ports import PolicyDecisionPort
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import EntityRow, ProductConceptRow


class SupplierMasterService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, request: SupplierProfileCreate) -> SupplierProfileRow:
        request_hash = request_fingerprint({"operation": "supplier_profile.create"}, request)
        existing = idempotent_row(
            self.session, SupplierProfileRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        entity = require_row(self.session, EntityRow, request.entity_id, "entity")
        if entity.status != "active" or entity.canonical_entity_id is not None:
            raise ValueError("supplier must reference an active canonical Entity")
        if entity.entity_type not in {"organization", "factory", "company"}:
            raise ValueError("supplier Entity must represent an organization")
        if self.session.scalar(
            select(SupplierProfileRow).where(SupplierProfileRow.entity_id == request.entity_id)
        ):
            raise ValueError("supplier profile already exists for this Entity")
        for evidence in request.evidence:
            require_row(self.session, ClaimRow, evidence.source_claim_id, "evidence Claim")
        for capability in request.capabilities:
            require_row(
                self.session, ProductConceptRow, capability.product_concept_id, "product concept"
            )
            require_row(self.session, ClaimRow, capability.source_claim_id, "evidence Claim")

        profile = SupplierProfileRow(
            id=new_id(),
            entity_id=request.entity_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            supplier_kind=request.supplier_kind.value,
            review_status=request.review_status.value,
            attributes_json=request.attributes,
            status="active",
        )
        self.session.add(profile)
        self.session.flush()
        self.session.add_all(
            [
                SupplierProfileEvidenceRow(
                    id=new_id(),
                    supplier_profile_id=profile.id,
                    field_path=item.field_path,
                    value_json=item.value,
                    source_claim_id=item.source_claim_id,
                    review_status=item.review_status.value,
                )
                for item in request.evidence
            ]
        )
        self.session.add_all(
            [
                SupplierCapabilityRow(
                    id=new_id(),
                    supplier_profile_id=profile.id,
                    product_concept_id=item.product_concept_id,
                    source_claim_id=item.source_claim_id,
                    specifications_json=item.specifications,
                    certifications_json=item.certifications,
                    capacity_json=item.capacity,
                    review_status=item.review_status.value,
                )
                for item in request.capabilities
            ]
        )
        self.session.commit()
        return profile

    def get(self, profile_id: str) -> SupplierProfileBundle:
        profile = require_row(self.session, SupplierProfileRow, profile_id, "supplier profile")
        evidence = self.session.scalars(
            select(SupplierProfileEvidenceRow)
            .where(SupplierProfileEvidenceRow.supplier_profile_id == profile_id)
            .order_by(SupplierProfileEvidenceRow.created_at, SupplierProfileEvidenceRow.id)
        ).all()
        capabilities = self.session.scalars(
            select(SupplierCapabilityRow)
            .where(SupplierCapabilityRow.supplier_profile_id == profile_id)
            .order_by(SupplierCapabilityRow.created_at, SupplierCapabilityRow.id)
        ).all()
        return SupplierProfileBundle(
            profile=profile,
            evidence=[
                {
                    "id": item.id,
                    "field_path": item.field_path,
                    "value": item.value_json,
                    "source_claim_id": item.source_claim_id,
                    "review_status": item.review_status,
                }
                for item in evidence
            ],
            capabilities=[
                {
                    "id": item.id,
                    "product_concept_id": item.product_concept_id,
                    "source_claim_id": item.source_claim_id,
                    "specifications": item.specifications_json,
                    "certifications": item.certifications_json,
                    "capacity": item.capacity_json,
                    "review_status": item.review_status,
                }
                for item in capabilities
            ],
        )


class SupplierDiscoveryService:
    def __init__(self, session: Session, policy: PolicyDecisionPort | None = None):
        self.session = session
        self.policy = policy

    def add_candidate(
        self, route_id: str, request: SupplierCandidateCreate
    ) -> SupplierCandidateRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        require_row(
            self.session, SupplierProfileRow, request.supplier_profile_id, "supplier profile"
        )
        request_hash = request_fingerprint(
            {"operation": "supplier_candidate.create", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, SupplierCandidateRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        if self.session.scalar(
            select(SupplierCandidateRow).where(
                SupplierCandidateRow.route_id == route_id,
                SupplierCandidateRow.supplier_profile_id == request.supplier_profile_id,
            )
        ):
            raise ValueError("supplier is already in this route's candidate pool")
        for claim_id in request.source_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "source Claim")
        row = SupplierCandidateRow(
            id=new_id(),
            route_id=route_id,
            supplier_profile_id=request.supplier_profile_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            discovery_basis_json=request.discovery_basis,
            source_claim_ids_json=request.source_claim_ids,
            missing_fields_json=sorted(set(request.missing_fields)),
            displayed_price_json=request.displayed_price,
            displayed_price_is_quote=False,
            status="candidate",
        )
        self.session.add(row)
        self.session.commit()
        return row

    def whitelist(
        self, candidate_id: str, request: CandidateWhitelistRequest
    ) -> SupplierCandidateRow:
        candidate = require_row(
            self.session, SupplierCandidateRow, candidate_id, "supplier candidate"
        )
        if self.policy is None:
            raise ValueError("a Board 8 policy port is required for supplier whitelisting")
        fingerprint = payload_hash(
            {
                "candidate_id": candidate.id,
                "route_id": candidate.route_id,
                "supplier_profile_id": candidate.supplier_profile_id,
            }
        )
        decision = self.policy.authorize(
            AuthorizationContext(
                action_kind="supplier_whitelist",
                resource_id=candidate.id,
                recipient_ref=candidate.supplier_profile_id,
                payload_hash=fingerprint,
                requested_by=request.requested_by,
            )
        )
        if decision.decision != "allow" or not decision.approved_by:
            raise ValueError("supplier whitelist policy did not return an approved allow decision")
        candidate.status = "whitelisted"
        candidate.whitelist_policy_ref = decision.policy_decision_ref
        candidate.whitelisted_by = decision.approved_by
        from tradefoundry.ingestion.models import utcnow

        candidate.whitelisted_at = utcnow()
        self.session.commit()
        return candidate


class SupplierPerformanceService:
    def __init__(self, session: Session):
        self.session = session

    def record_event(
        self, supplier_profile_id: str, request: PerformanceEventCreate
    ) -> SupplierPerformanceEventRow:
        require_row(self.session, SupplierProfileRow, supplier_profile_id, "supplier profile")
        require_row(self.session, ProductConceptRow, request.product_concept_id, "product concept")
        if request.evidence_claim_id:
            require_row(self.session, ClaimRow, request.evidence_claim_id, "evidence Claim")
        if request.actual is None and request.outcome is not None:
            raise ValueError("an outcome requires actual performance evidence")
        if request.actual is not None and request.outcome is None:
            raise ValueError("actual performance requires an explicit outcome")
        request_hash = request_fingerprint(
            {"operation": "supplier_performance.record", "supplier_id": supplier_profile_id},
            request,
        )
        existing = idempotent_row(
            self.session, SupplierPerformanceEventRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        row = SupplierPerformanceEventRow(
            id=new_id(),
            supplier_profile_id=supplier_profile_id,
            product_concept_id=request.product_concept_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            event_type=request.event_type,
            predicted_json=request.predicted,
            actual_json=request.actual,
            outcome=request.outcome,
            evidence_claim_id=request.evidence_claim_id,
            occurred_at=request.occurred_at,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def snapshot(
        self, supplier_profile_id: str, request: PerformanceSnapshotRequest
    ) -> SupplierPerformanceSnapshotRow:
        require_row(self.session, SupplierProfileRow, supplier_profile_id, "supplier profile")
        require_row(self.session, ProductConceptRow, request.product_concept_id, "product concept")
        request_hash = request_fingerprint(
            {"operation": "supplier_performance.snapshot", "supplier_id": supplier_profile_id},
            request,
        )
        existing = idempotent_row(
            self.session, SupplierPerformanceSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        events = self.session.scalars(
            select(SupplierPerformanceEventRow).where(
                SupplierPerformanceEventRow.supplier_profile_id == supplier_profile_id,
                SupplierPerformanceEventRow.product_concept_id == request.product_concept_id,
                SupplierPerformanceEventRow.occurred_at <= request.as_of,
            )
        ).all()
        actual_events = [item for item in events if item.actual_json is not None]
        successes = [item for item in actual_events if item.outcome == "success"]
        if len(actual_events) < request.minimum_history:
            score = None
            confidence_status = "insufficient_history"
        else:
            score = len(successes) / len(actual_events)
            confidence_status = "observed"
        row = SupplierPerformanceSnapshotRow(
            id=new_id(),
            supplier_profile_id=supplier_profile_id,
            product_concept_id=request.product_concept_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            event_count=len(events),
            actual_event_count=len(actual_events),
            successful_actual_count=len(successes),
            score=score,
            confidence_status=confidence_status,
            metrics_json={
                "minimum_history": request.minimum_history,
                "predicted_only_count": len(events) - len(actual_events),
                "failure_count": sum(item.outcome == "failure" for item in actual_events),
                "partial_count": sum(item.outcome == "partial" for item in actual_events),
                "event_types": sorted({item.event_type for item in events}),
                "as_of": aware(request.as_of).isoformat(),
            },
        )
        self.session.add(row)
        self.session.commit()
        return row
