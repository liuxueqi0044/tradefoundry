from __future__ import annotations

import csv
import io
import re
from datetime import UTC
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from typing import Any

from dateutil import parser as date_parser

from tradefoundry.bilateral.contracts import INCOTERMS_2020, QuoteParseResult


class SupplierQuoteParser:
    """Deterministic adapters for common key/value email, CSV and manual quote formats."""

    VERSION = "quote-parser-v1"
    ALIASES = {
        "currency": ("currency", "币种"),
        "unit_price": ("unit_price", "unit price", "单价"),
        "price_unit": ("price_unit", "price unit", "计价单位"),
        "total_amount": ("total_amount", "total amount", "总价"),
        "moq_quantity": ("moq", "moq_quantity", "最小起订量"),
        "moq_unit": ("moq_unit", "moq unit", "起订单位"),
        "lead_time_days": ("lead_time_days", "lead time days", "交期天数"),
        "tax": ("tax", "tax included", "含税"),
        "payment_terms": ("payment_terms", "payment terms", "付款条款"),
        "incoterm": ("incoterm", "贸易术语"),
        "valid_until": ("valid_until", "valid until", "有效期"),
    }
    REQUIRED = (
        "currency",
        "price",
        "tax",
        "moq",
        "lead_time_days",
        "payment_terms",
        "incoterm",
        "valid_until",
    )

    def parse_email(self, content: bytes) -> QuoteParseResult:
        message = BytesParser(policy=policy.default).parsebytes(content)
        body = message.get_body(preferencelist=("plain",)) if message.is_multipart() else message
        text = body.get_content() if body is not None else ""
        values: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"^\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$", line)
            if match:
                values[match.group(1).strip()] = match.group(2).strip()
        return self._normalize(values, "email")

    def parse_spreadsheet_csv(self, content: str | bytes) -> QuoteParseResult:
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader, None)
        if row is None:
            return QuoteParseResult(
                parser_version=self.VERSION,
                intake_format="spreadsheet",
                fields={},
                uncertain_fields=list(self.REQUIRED),
            )
        return self._normalize(dict(row), "spreadsheet")

    def parse_manual(self, values: dict[str, Any]) -> QuoteParseResult:
        return self._normalize(values, "manual")

    def _normalize(self, values: dict[str, Any], intake_format: str) -> QuoteParseResult:
        canonical = {str(key).strip().casefold(): value for key, value in values.items()}
        raw = {
            field: next(
                (canonical[alias.casefold()] for alias in aliases if alias.casefold() in canonical),
                None,
            )
            for field, aliases in self.ALIASES.items()
        }
        uncertain: list[str] = []
        fields: dict[str, Any] = {}
        currency = _text(raw["currency"])
        if currency and len(currency) == 3 and currency.isalpha():
            fields["currency"] = currency.upper()
        else:
            uncertain.append("currency")
        for field in ("unit_price", "total_amount", "moq_quantity"):
            if raw[field] not in (None, ""):
                parsed = _decimal(raw[field])
                if parsed is None:
                    uncertain.append(field)
                else:
                    fields[field] = str(parsed)
        if "unit_price" not in fields and "total_amount" not in fields:
            uncertain.append("price")
        if "unit_price" in fields:
            unit = _text(raw["price_unit"])
            if unit:
                fields["price_unit"] = unit
            else:
                uncertain.append("price_unit")
        if "moq_quantity" in fields:
            unit = _text(raw["moq_unit"])
            if unit:
                fields["moq_unit"] = unit
            else:
                uncertain.append("moq_unit")
        else:
            uncertain.append("moq")
        lead = _integer(raw["lead_time_days"])
        if lead is None:
            uncertain.append("lead_time_days")
        else:
            fields["lead_time_days"] = lead
        tax = _text(raw["tax"])
        if tax:
            fields["tax"] = {"raw": tax, "included": tax.casefold() in {"yes", "true", "含税"}}
        else:
            uncertain.append("tax")
        payment = _text(raw["payment_terms"])
        if payment:
            fields["payment_terms"] = payment
        else:
            uncertain.append("payment_terms")
        incoterm = _text(raw["incoterm"])
        if incoterm and incoterm.upper() in INCOTERMS_2020:
            fields["incoterm"] = incoterm.upper()
        else:
            uncertain.append("incoterm")
        valid_until = _datetime(raw["valid_until"])
        if valid_until is None:
            uncertain.append("valid_until")
        else:
            fields["valid_until"] = valid_until.isoformat()
        specifications = {
            key.split(".", 1)[1]: value
            for key, value in canonical.items()
            if key.startswith("spec.") and value not in (None, "")
        }
        fields["specifications"] = specifications
        return QuoteParseResult(
            parser_version=self.VERSION,
            intake_format=intake_format,
            fields=fields,
            uncertain_fields=sorted(set(uncertain)),
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _datetime(value: Any):
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = date_parser.parse(text)
    except (ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
