from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.ingestion.hashing import payload_hash

MONEY_QUANTUM = Decimal("0.0001")
QUANTITY_QUANTUM = Decimal("0.000001")


def new_id() -> str:
    return str(uuid4())


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantity(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def request_fingerprint(scope: dict[str, Any], request: Any) -> str:
    payload = request.model_dump(mode="json") if hasattr(request, "model_dump") else request
    return payload_hash({**scope, **payload})


def idempotent_row(session: Session, row_type, idempotency_key: str, request_hash: str):
    existing = session.scalar(select(row_type).where(row_type.idempotency_key == idempotency_key))
    if existing is not None and existing.request_hash != request_hash:
        raise ValueError("idempotency key was reused with different inputs")
    return existing


def require_row(session: Session, row_type, row_id: str, label: str):
    row = session.get(row_type, row_id)
    if row is None:
        raise LookupError(f"{label} {row_id} was not found")
    return row
