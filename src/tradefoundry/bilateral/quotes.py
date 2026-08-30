from __future__ import annotations

from decimal import Decimal

from pint import DimensionalityError, UnitRegistry
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    aware,
    idempotent_row,
    money,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import QuoteComparisonRequest, SupplierQuoteIntake
from tradefoundry.bilateral.models import (
    QuoteComparisonRow,
    RfqVersionRow,
    SupplierProfileRow,
    SupplierQuoteRow,
)
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.ingestion.hashing import payload_hash

UNIT_REGISTRY = UnitRegistry()


class SupplierQuoteService:
    REQUIRED_STRUCTURED_FIELDS = (
        "currency",
        "price",
        "tax",
        "moq",
        "lead_time_days",
        "payment_terms",
        "incoterm",
        "valid_until",
    )

    def __init__(self, session: Session):
        self.session = session

    def intake(self, route_id: str, request: SupplierQuoteIntake) -> SupplierQuoteRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        require_row(
            self.session, SupplierProfileRow, request.supplier_profile_id, "supplier profile"
        )
        if request.rfq_version_id:
            rfq = require_row(self.session, RfqVersionRow, request.rfq_version_id, "RFQ")
            if rfq.route_id != route_id:
                raise ValueError("RFQ belongs to another route")
        if request.valid_until and aware(request.valid_until) <= aware(request.received_at):
            raise ValueError("quote valid_until must be after received_at")
        request_hash = request_fingerprint(
            {"operation": "supplier_quote.intake", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, SupplierQuoteRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        missing = {
            "currency": request.currency is None,
            "price": request.unit_price is None and request.total_amount is None,
            "tax": request.tax is None,
            "moq": request.moq_quantity is None,
            "lead_time_days": request.lead_time_days is None,
            "payment_terms": request.payment_terms is None,
            "incoterm": request.incoterm is None,
            "valid_until": request.valid_until is None,
        }
        uncertain = sorted(
            set(request.uncertain_fields) | {name for name, absent in missing.items() if absent}
        )
        row = SupplierQuoteRow(
            id=new_id(),
            route_id=route_id,
            supplier_profile_id=request.supplier_profile_id,
            rfq_version_id=request.rfq_version_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            intake_format=request.intake_format,
            raw_artifact_ref=request.raw_artifact_ref,
            raw_hash=request.raw_hash,
            currency=request.currency,
            unit_price=request.unit_price,
            price_unit=request.price_unit,
            total_amount=request.total_amount,
            moq_quantity=request.moq_quantity,
            moq_unit=request.moq_unit,
            lead_time_days=request.lead_time_days,
            tax_json=request.tax,
            payment_terms=request.payment_terms,
            incoterm=request.incoterm,
            valid_until=request.valid_until,
            specifications_json=request.specifications,
            uncertain_fields_json=uncertain,
            review_status="needs_review" if uncertain else "structured",
            received_at=request.received_at,
        )
        self.session.add(row)
        self.session.commit()
        return row


class QuoteComparisonService:
    def __init__(self, session: Session):
        self.session = session

    def compare(self, route_id: str, request: QuoteComparisonRequest) -> QuoteComparisonRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        request_hash = request_fingerprint(
            {"operation": "supplier_quote.compare", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, QuoteComparisonRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        if len(set(request.quote_ids)) != len(request.quote_ids):
            raise ValueError("quote_ids must not contain duplicates")
        quotes = [
            require_row(self.session, SupplierQuoteRow, quote_id, "supplier quote")
            for quote_id in request.quote_ids
        ]
        if any(quote.route_id != route_id for quote in quotes):
            raise ValueError("all quotes must belong to the requested route")
        rate_map: dict[tuple[str, str], tuple[Decimal, dict]] = {}
        conversion_snapshot: dict[str, dict] = {}
        for rate in request.fx_rates:
            key = (rate.base_currency, rate.quote_currency)
            if key in rate_map:
                raise ValueError(f"duplicate FX rate {key[0]}/{key[1]}")
            snapshot = rate.model_dump(mode="json")
            rate_map[key] = (rate.rate, snapshot)
            conversion_snapshot[f"{key[0]}/{key[1]}"] = snapshot

        rows: list[dict] = []
        incomparable: list[str] = []
        assumptions: list[str] = []
        for quote in quotes:
            row, row_assumptions = self._normalize_quote(
                quote,
                request=request,
                rate_map=rate_map,
            )
            rows.append(row)
            assumptions.extend(row_assumptions)
            if not row["comparable"]:
                incomparable.append(quote.id)
        spec_differences = _specification_differences(quotes)
        result = QuoteComparisonRow(
            id=new_id(),
            route_id=route_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            quote_ids_json=request.quote_ids,
            target_currency=request.target_currency,
            target_unit=request.target_unit,
            target_incoterm=request.target_incoterm,
            conversion_snapshot_json={
                "fx": conversion_snapshot,
                "unit_registry": "pint",
                "unit_context": request.unit_context,
                "incoterm_adjustments": {
                    key: str(value) for key, value in request.incoterm_adjustments.items()
                },
                "snapshot_hash": payload_hash(
                    {
                        "fx": conversion_snapshot,
                        "target_unit": request.target_unit,
                        "target_incoterm": request.target_incoterm,
                        "adjustments": request.incoterm_adjustments,
                    }
                ),
            },
            rows_json=rows,
            specification_differences_json=spec_differences,
            assumptions_json=sorted(set(assumptions)),
            incomparable_quote_ids_json=incomparable,
        )
        self.session.add(result)
        self.session.commit()
        return result

    def _normalize_quote(self, quote, *, request, rate_map):
        reasons: list[str] = []
        assumptions: list[str] = []
        if quote.unit_price is None or quote.currency is None or quote.price_unit is None:
            reasons.append("missing unit price, currency, or price unit")
        if quote.incoterm is None:
            reasons.append("missing Incoterm")
        converted_price: Decimal | None = None
        fx_rate: Decimal | None = None
        unit_factor: Decimal | None = None
        if not reasons:
            try:
                unit_factor = Decimal(
                    str(
                        (1 * UNIT_REGISTRY(request.target_unit))
                        .to(UNIT_REGISTRY(quote.price_unit))
                        .magnitude
                    )
                )
            except (DimensionalityError, ValueError, TypeError, AttributeError) as exc:
                reasons.append(f"incompatible unit conversion: {exc}")
            if quote.currency == request.target_currency:
                fx_rate = Decimal("1")
            else:
                direct = rate_map.get((quote.currency, request.target_currency))
                inverse = rate_map.get((request.target_currency, quote.currency))
                if direct:
                    fx_rate = direct[0]
                    assumptions.append(
                        f"quote {quote.id} uses FX {quote.currency}/"
                        f"{request.target_currency} from {direct[1]['source_ref']}"
                    )
                elif inverse:
                    fx_rate = Decimal("1") / inverse[0]
                    assumptions.append(
                        f"quote {quote.id} uses inverse FX {request.target_currency}/"
                        f"{quote.currency} from {inverse[1]['source_ref']}"
                    )
                else:
                    reasons.append(f"missing FX rate {quote.currency}/{request.target_currency}")
            adjustment = Decimal("0")
            if quote.incoterm != request.target_incoterm:
                if quote.id not in request.incoterm_adjustments:
                    reasons.append(
                        f"missing explicit {quote.incoterm}-to-{request.target_incoterm} adjustment"
                    )
                else:
                    adjustment = request.incoterm_adjustments[quote.id]
                    assumptions.append(
                        f"quote {quote.id} applies explicit Incoterm adjustment "
                        f"{adjustment} {request.target_currency}/{request.target_unit}"
                    )
            if not reasons and fx_rate is not None and unit_factor is not None:
                converted_price = money(quote.unit_price * unit_factor * fx_rate + adjustment)
                assumptions.append(
                    f"quote {quote.id} unit conversion factor is {unit_factor} "
                    f"{quote.price_unit}/{request.target_unit}"
                )
        return (
            {
                "quote_id": quote.id,
                "supplier_profile_id": quote.supplier_profile_id,
                "source": {
                    "unit_price": str(quote.unit_price) if quote.unit_price is not None else None,
                    "currency": quote.currency,
                    "price_unit": quote.price_unit,
                    "incoterm": quote.incoterm,
                },
                "normalized": {
                    "unit_price": str(converted_price) if converted_price is not None else None,
                    "currency": request.target_currency,
                    "price_unit": request.target_unit,
                    "incoterm": request.target_incoterm,
                    "fx_rate": str(fx_rate) if fx_rate is not None else None,
                    "unit_factor": str(unit_factor) if unit_factor is not None else None,
                },
                "comparable": not reasons,
                "reasons": reasons,
                "uncertain_fields": quote.uncertain_fields_json,
            },
            assumptions,
        )


def _specification_differences(quotes: list[SupplierQuoteRow]) -> dict:
    keys = sorted({key for quote in quotes for key in quote.specifications_json})
    return {
        key: {
            quote.id: quote.specifications_json.get(key)
            for quote in quotes
            if key in quote.specifications_json
        }
        for key in keys
        if len(
            {
                repr(quote.specifications_json.get(key))
                for quote in quotes
                if key in quote.specifications_json
            }
        )
        > 1
        or any(key not in quote.specifications_json for quote in quotes)
    }
