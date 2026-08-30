from sqlalchemy.orm import Session

from tradefoundry.evidence.models import ClaimRow


def require_reliable_claim(session: Session, claim_id: str) -> ClaimRow:
    claim = session.get(ClaimRow, claim_id)
    if claim is None:
        raise LookupError(f"Claim {claim_id} not found")
    if claim.status not in {"validated", "verified"}:
        raise ValueError(
            f"Claim {claim_id} has status {claim.status}; master data requires validated evidence"
        )
    return claim
