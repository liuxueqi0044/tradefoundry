from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimEvidenceRow, ClaimRow
from tradefoundry.execution.common import aware, new_id, utcnow
from tradefoundry.execution.contracts_orders import ShipmentDocument
from tradefoundry.execution.models_orders import ExecutionReviewIssueRow, ShipmentDocumentRow

REQUIRED_DOCUMENTS = {"invoice", "packing_list", "bill_of_lading", "customs", "certificate"}


class ShipmentDocumentService:
    def __init__(self, session: Session):
        self.session = session

    def add(self, document: ShipmentDocument) -> ShipmentDocumentRow:
        existing = self.session.scalar(
            select(ShipmentDocumentRow).where(
                ShipmentDocumentRow.shipment_id == document.shipment_id,
                ShipmentDocumentRow.document_type == document.document_type,
                ShipmentDocumentRow.version_no == document.version_no,
            )
        )
        if existing is not None:
            expected = (
                document.storage_ref,
                document.content_hash,
                document.evidence.claim_id,
                document.evidence.evidence_fragment_ids,
                aware(document.expires_at) if document.expires_at else None,
                document.related_document_versions,
                document.sensitive_fields,
            )
            actual = (
                existing.storage_ref,
                existing.content_hash,
                existing.evidence_claim_id,
                existing.evidence_fragment_ids_json,
                aware(existing.expires_at) if existing.expires_at else None,
                existing.related_document_versions_json,
                existing.sensitive_fields_json,
            )
            if actual != expected:
                raise ValueError("shipment-document version was reused with different facts")
            return existing
        claim = self.session.get(ClaimRow, document.evidence.claim_id)
        if claim is None or claim.status != "verified":
            raise ValueError("a verified shipment-document evidence Claim is required")
        fragments = set(
            self.session.scalars(
                select(ClaimEvidenceRow.fragment_id).where(ClaimEvidenceRow.claim_id == claim.id)
            )
        )
        if not set(document.evidence.evidence_fragment_ids).issubset(fragments):
            raise ValueError("shipment-document evidence must belong to the verified Claim")
        row = ShipmentDocumentRow(
            id=new_id(),
            shipment_id=document.shipment_id,
            document_type=document.document_type,
            version_no=document.version_no,
            storage_ref=document.storage_ref,
            content_hash=document.content_hash,
            evidence_claim_id=document.evidence.claim_id,
            evidence_fragment_ids_json=document.evidence.evidence_fragment_ids,
            expires_at=aware(document.expires_at) if document.expires_at else None,
            related_document_versions_json=document.related_document_versions,
            sensitive_fields_json=document.sensitive_fields,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def validate(self, shipment_id: str, *, now=None) -> list[ExecutionReviewIssueRow]:
        now = aware(now or utcnow())
        rows = list(
            self.session.scalars(
                select(ShipmentDocumentRow).where(ShipmentDocumentRow.shipment_id == shipment_id)
            )
        )
        latest = {
            kind: max(
                (row for row in rows if row.document_type == kind), key=lambda row: row.version_no
            )
            for kind in {row.document_type for row in rows}
        }
        issues: list[ExecutionReviewIssueRow] = []
        missing = sorted(REQUIRED_DOCUMENTS - set(latest))
        if missing:
            issues.append(self._issue(shipment_id, "missing_documents", {"missing": missing}))
        expired = sorted(
            kind for kind, row in latest.items() if row.expires_at and aware(row.expires_at) < now
        )
        if expired:
            issues.append(self._issue(shipment_id, "expired_documents", {"expired": expired}))
        inconsistent = {
            kind: {
                other: expected
                for other, expected in row.related_document_versions_json.items()
                if other not in latest or latest[other].version_no != expected
            }
            for kind, row in latest.items()
        }
        inconsistent = {kind: value for kind, value in inconsistent.items() if value}
        if inconsistent:
            issues.append(self._issue(shipment_id, "document_version_inconsistency", inconsistent))
        self.session.commit()
        return issues

    def view(self, document_id: str, *, roles: set[str]) -> dict:
        row = self.session.get(ShipmentDocumentRow, document_id)
        if row is None:
            raise LookupError(f"shipment document {document_id} was not found")
        visible = (
            dict(row.sensitive_fields_json)
            if "execution_sensitive_reader" in roles
            else {key: "[REDACTED]" for key in row.sensitive_fields_json}
        )
        storage_ref = row.storage_ref if "execution_sensitive_reader" in roles else "[REDACTED]"
        return {
            "id": row.id,
            "shipment_id": row.shipment_id,
            "document_type": row.document_type,
            "version_no": row.version_no,
            "storage_ref": storage_ref,
            "sensitive_fields": visible,
        }

    def _issue(self, shipment_id: str, issue_type: str, details: dict) -> ExecutionReviewIssueRow:
        existing = self.session.scalar(
            select(ExecutionReviewIssueRow).where(
                ExecutionReviewIssueRow.issue_type == issue_type,
                ExecutionReviewIssueRow.resource_ref == f"shipment:{shipment_id}",
                ExecutionReviewIssueRow.status == "open",
            )
        )
        if existing is not None and existing.details_json == details:
            return existing
        row = ExecutionReviewIssueRow(
            id=new_id(),
            issue_type=issue_type,
            resource_ref=f"shipment:{shipment_id}",
            details_json=details,
        )
        self.session.add(row)
        return row
