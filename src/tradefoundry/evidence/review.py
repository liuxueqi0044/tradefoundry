from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.contracts import ClaimView, ReviewRequest
from tradefoundry.evidence.models import (
    ClaimEvidenceRow,
    ClaimRow,
    ConflictGroupRow,
    EvidenceFragmentRow,
    ExtractionSchemaRow,
    ReviewDecisionRow,
)
from tradefoundry.evidence.normalization import ClaimNormalizer


class ClaimReviewService:
    def __init__(self, session: Session):
        self.session = session
        self.normalizer = ClaimNormalizer()

    def review(self, claim_id: str, request: ReviewRequest) -> ClaimView:
        claim = self.session.get(ClaimRow, claim_id)
        if claim is None:
            raise LookupError(f"claim {claim_id} not found")
        if claim.status in {"rejected", "corrected"}:
            raise ValueError(f"claim in final status {claim.status} cannot be reviewed again")
        previous_status = claim.status
        resulting_claim = claim

        if request.action == "verify":
            claim.status = "verified"
            self._resolve_conflict(claim, request)
        elif request.action == "reject":
            claim.status = "rejected"
        else:
            resulting_claim = self._correct(claim, request)
            claim.status = "corrected"

        decision = ReviewDecisionRow(
            id=str(uuid4()),
            claim_id=claim.id,
            action=request.action,
            reviewer=request.reviewer,
            reason=request.reason,
            previous_status=previous_status,
            resulting_claim_id=resulting_claim.id,
            details_json={
                "corrected_value": request.corrected_value if request.action == "correct" else None,
                "evidence": request.evidence,
            },
        )
        self.session.add(decision)
        self.session.commit()
        return ClaimView.model_validate(resulting_claim)

    def _correct(self, original: ClaimRow, request: ReviewRequest) -> ClaimRow:
        schema = self.session.get(ExtractionSchemaRow, original.schema_id)
        if schema is None:
            raise LookupError(f"schema {original.schema_id} not found")
        rule = schema.field_rules.get(original.field_path, {})
        normalized = self.normalizer.normalize(request.corrected_value, rule)
        if normalized.status != "normalized":
            raise ValueError(
                f"corrected value is not valid: {normalized.reason or normalized.status}"
            )
        corrected = ClaimRow(
            id=str(uuid4()),
            document_id=original.document_id,
            extraction_run_id=None,
            schema_id=original.schema_id,
            subject_key=original.subject_key,
            field_path=original.field_path,
            value_json=request.corrected_value,
            normalized_value_json=normalized.value,
            normalization_status=normalized.status,
            unit=normalized.unit,
            currency=normalized.currency,
            confidence=1.0,
            method="human_review",
            method_version=None,
            status="verified",
            valid_from=original.valid_from,
            valid_to=original.valid_to,
            supersedes_claim_id=original.id,
            conflict_group_id=original.conflict_group_id,
        )
        self.session.add(corrected)
        self.session.flush()
        fragment_ids = self._evidence_ids(original, request.evidence)
        for fragment_id in fragment_ids:
            self.session.add(
                ClaimEvidenceRow(id=str(uuid4()), claim_id=corrected.id, fragment_id=fragment_id)
            )
        if corrected.conflict_group_id:
            group = self.session.get(ConflictGroupRow, corrected.conflict_group_id)
            if group:
                group.status = "resolved"
                group.resolution_json = {
                    "claim_id": corrected.id,
                    "reviewer": request.reviewer,
                    "reason": request.reason,
                }
        return corrected

    def _evidence_ids(self, claim: ClaimRow, requested: list[str] | None) -> list[str]:
        if requested is None:
            return list(
                self.session.scalars(
                    select(ClaimEvidenceRow.fragment_id).where(
                        ClaimEvidenceRow.claim_id == claim.id
                    )
                ).all()
            )
        rows = self.session.scalars(
            select(EvidenceFragmentRow).where(
                EvidenceFragmentRow.document_id == claim.document_id,
                EvidenceFragmentRow.fragment_key.in_(requested),
            )
        ).all()
        found = {row.fragment_key: row.id for row in rows}
        missing = [key for key in requested if key not in found]
        if missing:
            raise ValueError(f"unknown evidence fragments: {missing}")
        if not requested:
            raise ValueError("a corrected Claim requires at least one evidence fragment")
        return [found[key] for key in dict.fromkeys(requested)]

    def _resolve_conflict(self, claim: ClaimRow, request: ReviewRequest) -> None:
        if not claim.conflict_group_id:
            return
        group = self.session.get(ConflictGroupRow, claim.conflict_group_id)
        if group:
            group.status = "resolved"
            group.resolution_json = {
                "claim_id": claim.id,
                "reviewer": request.reviewer,
                "reason": request.reason,
            }
