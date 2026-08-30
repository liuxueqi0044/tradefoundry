from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash

MONEY_QUANTUM = Decimal("0.0001")


def aware(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive values to UTC for safe comparisons."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def request_fingerprint(scope: dict[str, Any], request: Any) -> str:
    return payload_hash({**scope, **request.model_dump(mode="json")})


def idempotent_row(session: Session, row_type, idempotency_key: str, request_hash: str):
    existing = session.scalar(select(row_type).where(row_type.idempotency_key == idempotency_key))
    if existing is not None and existing.request_hash != request_hash:
        raise ValueError("idempotency key was reused with different inputs")
    return existing
