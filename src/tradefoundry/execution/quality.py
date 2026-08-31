"""Quality, claim and dispute case ledger (S9.8)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import idempotent_row, money, new_id, request_fingerprint
from tradefoundry.execution.contracts_settlement import (
    QualityCaseCreate,
    QualityClose,
    QualityEventCreate,
)
from tradefoundry.execution.models_settlement import (
    QualityCaseEventRow,
    QualityCaseRow,
    QualityReserveRow,
)
from tradefoundry.execution.settlement import InvoiceSettlementService


class QualityCaseService:
    def __init__(self, session: Session):
        self.session = session

    def open_case(self, request: QualityCaseCreate) -> QualityCaseRow:
        request_hash = request_fingerprint({"operation": "execution.quality.open"}, request)
        existing = idempotent_row(
            self.session, QualityCaseRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        InvoiceSettlementService._require_order(self.session, request.order_id)
        # These four references are deliberately mandatory: a free-floating
        # complaint cannot be attributed to a transaction or supplier/buyer.
        for name in ("order_id", "batch_ref", "supplier_ref", "buyer_ref"):
            if not getattr(request, name).strip():
                raise ValueError(f"{name} is required for a quality case")
        row = QualityCaseRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            order_id=request.order_id,
            batch_ref=request.batch_ref,
            supplier_ref=request.supplier_ref,
            buyer_ref=request.buyer_ref,
            case_type=request.case_type,
            description=request.description,
            reported_by=request.reported_by,
            evidence_refs_json=list(request.evidence_refs),
            status="open",
            currency=request.currency.upper(),
            reserve_amount=money(request.reserve_amount),
            final_loss=money(0),
        )
        self.session.add(row)
        self.session.flush()
        if request.reserve_amount:
            self.session.add(
                QualityReserveRow(
                    id=new_id(),
                    case_id=row.id,
                    amount=money(request.reserve_amount),
                    currency=request.currency.upper(),
                    evidence_refs_json=list(request.evidence_refs),
                )
            )
        self.session.commit()
        return row

    create_case = open_case

    def append_event(self, request: QualityEventCreate) -> QualityCaseEventRow:
        request_hash = request_fingerprint({"operation": "execution.quality.event"}, request)
        existing = idempotent_row(
            self.session, QualityCaseEventRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        case = self.session.get(QualityCaseRow, request.case_id)
        if case is None:
            raise LookupError(f"quality case {request.case_id} was not found")
        if case.status == "closed":
            raise ValueError("closed quality cases are immutable")
        if request.amount is not None and request.currency is None:
            raise ValueError("an event amount requires a currency")
        row = QualityCaseEventRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            case_id=case.id,
            event_type=request.event_type,
            description=request.description,
            evidence_refs_json=list(request.evidence_refs),
            amount=money(request.amount) if request.amount is not None else None,
            currency=request.currency.upper() if request.currency else None,
        )
        self.session.add(row)
        self.session.commit()
        return row

    add_event = append_event

    def close_case(self, request: QualityClose) -> QualityCaseRow:
        close_hash = request_fingerprint({"operation": "execution.quality.close"}, request)
        prior_close = idempotent_row(
            self.session, QualityCaseEventRow, request.idempotency_key, close_hash
        )
        case = self.session.get(QualityCaseRow, request.case_id)
        if case is None:
            raise LookupError(f"quality case {request.case_id} was not found")
        if prior_close is not None:
            return case
        if case.status == "closed":
            if (
                case.conclusion != request.conclusion
                or case.independent_reviewer != request.independent_reviewer
                or case.close_evidence_refs_json != list(request.evidence_refs)
                or case.final_loss != money(request.final_loss)
                or (request.currency or case.currency).upper() != case.currency.upper()
            ):
                raise ValueError("closed case cannot be changed")
            return case
        if not request.conclusion.strip() or not request.independent_reviewer.strip():
            raise ValueError("case closure requires an independent conclusion and reviewer")
        if request.independent_reviewer == case.reported_by:
            raise ValueError("quality case reporter cannot independently close the case")
        if not request.evidence_refs:
            raise ValueError("case closure requires evidence")
        currency = (request.currency or case.currency).upper()
        if currency != case.currency.upper():
            raise ValueError("final loss currency must match the case currency")
        case.status = "closed"
        case.conclusion = request.conclusion
        case.independent_reviewer = request.independent_reviewer
        case.close_evidence_refs_json = list(request.evidence_refs)
        case.final_loss = money(request.final_loss)
        from datetime import UTC, datetime

        case.closed_at = datetime.now(UTC)
        # Closing is itself an append-only event, and PnL consumes this value.
        self.session.add(
            QualityCaseEventRow(
                id=new_id(),
                idempotency_key=request.idempotency_key,
                request_hash=close_hash,
                case_id=case.id,
                event_type="case_closed",
                description=request.conclusion,
                evidence_refs_json=list(request.evidence_refs),
                amount=case.final_loss,
                currency=currency,
            )
        )
        self.session.commit()
        return case

    close = close_case

    def list_events(self, case_id: str) -> list[QualityCaseEventRow]:
        return list(
            self.session.scalars(
                select(QualityCaseEventRow)
                .where(QualityCaseEventRow.case_id == case_id)
                .order_by(QualityCaseEventRow.created_at, QualityCaseEventRow.id)
            )
        )


QualityService = QualityCaseService

__all__ = ["QualityCaseService", "QualityService"]
