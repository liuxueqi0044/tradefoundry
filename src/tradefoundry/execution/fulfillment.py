from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimEvidenceRow, ClaimRow
from tradefoundry.execution.common import aware, new_id, quantity
from tradefoundry.execution.contracts_orders import MilestoneRecord
from tradefoundry.execution.models_orders import FulfillmentMilestoneRow


class FulfillmentService:
    def __init__(self, session: Session):
        self.session = session

    def record(self, record: MilestoneRecord) -> FulfillmentMilestoneRow:
        existing = self.session.scalar(
            select(FulfillmentMilestoneRow).where(
                FulfillmentMilestoneRow.shipment_id == record.shipment_id,
                FulfillmentMilestoneRow.milestone_key == record.milestone_key,
                FulfillmentMilestoneRow.version_no == record.version_no,
            )
        )
        if existing is not None:
            expected = (
                aware(record.planned_at),
                aware(record.actual_at) if record.actual_at else None,
                quantity(record.planned_quantity),
                quantity(record.actual_quantity),
                record.quantity_unit,
                record.evidence.claim_id,
                record.evidence.evidence_fragment_ids,
            )
            actual = (
                aware(existing.planned_at),
                aware(existing.actual_at) if existing.actual_at else None,
                existing.planned_quantity,
                existing.actual_quantity,
                existing.quantity_unit,
                existing.evidence_claim_id,
                existing.evidence_fragment_ids_json,
            )
            if actual != expected:
                raise ValueError("milestone version was reused with different facts")
            return existing
        claim = self.session.get(ClaimRow, record.evidence.claim_id)
        if claim is None or claim.status != "verified":
            raise ValueError("a verified milestone evidence Claim is required")
        fragments = set(
            self.session.scalars(
                select(ClaimEvidenceRow.fragment_id).where(ClaimEvidenceRow.claim_id == claim.id)
            )
        )
        if not set(record.evidence.evidence_fragment_ids).issubset(fragments):
            raise ValueError("milestone evidence must belong to the verified Claim")
        actual = quantity(record.actual_quantity)
        planned = quantity(record.planned_quantity)
        late_days = (
            None
            if record.actual_at is None
            else max(0, (aware(record.actual_at).date() - aware(record.planned_at).date()).days)
        )
        delivery_status = (
            "planned"
            if record.actual_at is None
            else ("complete" if actual == planned else "partial")
        )
        row = FulfillmentMilestoneRow(
            id=new_id(),
            shipment_id=record.shipment_id,
            milestone_key=record.milestone_key,
            version_no=record.version_no,
            planned_at=aware(record.planned_at),
            actual_at=aware(record.actual_at) if record.actual_at else None,
            planned_quantity=planned,
            actual_quantity=actual,
            quantity_unit=record.quantity_unit,
            late_days=late_days,
            delivery_status=delivery_status,
            evidence_claim_id=record.evidence.claim_id,
            evidence_fragment_ids_json=record.evidence.evidence_fragment_ids,
        )
        self.session.add(row)
        self.session.commit()
        return row
