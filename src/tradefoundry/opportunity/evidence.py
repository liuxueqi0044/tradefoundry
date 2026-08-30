from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimEvidenceRow, ClaimRow


def require_verified_claim(
    session: Session, claim_id: str, *, original_link: bool = True
) -> ClaimRow:
    claim = session.get(ClaimRow, claim_id)
    if claim is None:
        raise LookupError(f"Claim {claim_id} not found")
    if claim.status != "verified":
        raise ValueError(
            f"Claim {claim_id} has status {claim.status}; a verified Claim is required"
        )
    if original_link:
        count = session.scalar(
            select(func.count())
            .select_from(ClaimEvidenceRow)
            .where(ClaimEvidenceRow.claim_id == claim_id)
        )
        if not count:
            raise ValueError(f"Claim {claim_id} has no original evidence fragment")
    return claim
