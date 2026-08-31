"""Human-governed business review proposals."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import idempotent_row, new_id, request_fingerprint, utcnow
from tradefoundry.execution.contracts_learning import ReviewProposalRequest, ReviewProposalView
from tradefoundry.execution.models_learning import ReviewProposalRow


class ReviewProposalService:
    def __init__(self, session: Session):
        self.session = session

    def propose(self, request: ReviewProposalRequest) -> ReviewProposalView:
        request_hash = request_fingerprint({"service": "review"}, request)
        existing = idempotent_row(
            self.session, ReviewProposalRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return ReviewProposalView.model_validate(existing)
        row = ReviewProposalRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            proposal_type=request.proposal_type,
            subject_ref=request.subject_ref,
            proposal_json=request.proposal,
            evidence_refs_json=request.evidence_refs,
            status="review_pending",
            created_by=request.created_by,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return ReviewProposalView.model_validate(row)

    create = propose

    def list_pending(self) -> list[ReviewProposalView]:
        return [
            ReviewProposalView.model_validate(row)
            for row in self.session.scalars(
                select(ReviewProposalRow)
                .where(ReviewProposalRow.status == "review_pending")
                .order_by(ReviewProposalRow.created_at, ReviewProposalRow.id)
            )
        ]

    def apply(self, proposal_id: str) -> None:
        """There is deliberately no automatic application path."""
        raise PermissionError(
            f"review proposal {proposal_id} requires an authorised human decision"
        )


# Short aliases make the boundary convenient for API adapters without duplicating logic.
ReviewService = ReviewProposalService
