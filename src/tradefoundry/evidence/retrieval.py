from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.conflicts import ConflictService
from tradefoundry.evidence.contracts import (
    ClaimView,
    EvidenceLocation,
    EvidencePackage,
)
from tradefoundry.evidence.models import (
    ClaimEvidenceRow,
    ClaimRow,
    EvidenceDocumentRow,
    EvidenceFragmentRow,
)
from tradefoundry.ingestion.models import ArtifactBlobRow


class EvidenceRetrievalService:
    def __init__(self, session: Session):
        self.session = session

    def package(self, claim_id: str) -> EvidencePackage:
        claim = self.session.get(ClaimRow, claim_id)
        if claim is None:
            raise LookupError(f"claim {claim_id} not found")
        document = self.session.get(EvidenceDocumentRow, claim.document_id)
        if document is None or document.artifact_sha256 is None:
            raise LookupError(f"source document for Claim {claim_id} is unavailable")
        artifact = self.session.get(ArtifactBlobRow, document.artifact_sha256)
        if artifact is None:
            raise LookupError(f"artifact {document.artifact_sha256} is unavailable")
        fragments = self.session.scalars(
            select(EvidenceFragmentRow)
            .join(ClaimEvidenceRow, ClaimEvidenceRow.fragment_id == EvidenceFragmentRow.id)
            .where(ClaimEvidenceRow.claim_id == claim.id)
            .order_by(EvidenceFragmentRow.page_no, EvidenceFragmentRow.fragment_key)
        ).all()
        locations = [
            EvidenceLocation(
                fragment_id=fragment.id,
                fragment_key=fragment.fragment_key,
                fragment_type=fragment.fragment_type,
                text=fragment.text,
                page_no=fragment.page_no,
                bbox=fragment.bbox_json,
                section_path=fragment.section_path,
                table_cell=fragment.table_cell_json,
            )
            for fragment in fragments
        ]
        reason = self._support_reason(claim, locations)
        return EvidencePackage(
            claim_id=claim.id,
            supported=reason is None,
            support_reason=reason,
            conclusion=claim.value_json,
            normalized_conclusion=claim.normalized_value_json,
            claim_status=claim.status,
            document_id=document.id,
            logical_document_id=document.logical_document_id,
            document_version=document.version_no,
            artifact_sha256=document.artifact_sha256,
            artifact_uri=artifact.uri,
            locations=locations,
        )

    def claims_as_of(self, subject_key: str, at: datetime) -> list[ClaimView]:
        return [
            ClaimView.model_validate(row)
            for row in ConflictService(self.session).as_of(subject_key, at)
        ]

    @staticmethod
    def _support_reason(claim: ClaimRow, locations: list[EvidenceLocation]) -> str | None:
        if not locations:
            return "no_evidence_location"
        if claim.status in {"rejected", "corrected"}:
            return f"claim_status_{claim.status}"
        if claim.status == "conflict":
            return "claim_is_disputed"
        if claim.status in {"candidate", "needs_review"}:
            return "claim_not_validated"
        return None
