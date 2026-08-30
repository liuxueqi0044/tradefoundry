from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Any

import pint
from dateutil import parser as date_parser
from moneyed import CurrencyDoesNotExist, get_currency


@dataclass(frozen=True)
class NormalizationResult:
    value: Any | None
    status: str
    unit: str | None = None
    currency: str | None = None
    reason: str | None = None


class ClaimNormalizer:
    def __init__(self):
        self.units = pint.UnitRegistry()

    def normalize(self, value: Any, rule: dict[str, Any] | None) -> NormalizationResult:
        rule = rule or {}
        kind = rule.get("type", "identity")
        try:
            if kind == "date":
                return self._date(value)
            if kind == "decimal":
                return self._decimal(value)
            if kind == "currency":
                return self._currency(value)
            if kind == "quantity":
                return self._quantity(value, rule)
            if kind == "string":
                return NormalizationResult(str(value).strip(), "normalized")
            return NormalizationResult(value, "normalized")
        except (InvalidOperation, TypeError, ValueError, pint.PintError) as exc:
            return NormalizationResult(None, "invalid", reason=str(exc))

    @staticmethod
    def _date(value: Any) -> NormalizationResult:
        raw = str(value).strip()
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
        if match and int(match.group(1)) <= 12 and int(match.group(2)) <= 12:
            return NormalizationResult(None, "needs_review", reason="ambiguous numeric date")
        parsed = date_parser.parse(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return NormalizationResult(parsed.isoformat(), "normalized")

    @staticmethod
    def _decimal(value: Any) -> NormalizationResult:
        normalized = Decimal(str(value).replace(",", "").strip())
        return NormalizationResult(format(normalized, "f"), "normalized")

    @staticmethod
    def _currency(value: Any) -> NormalizationResult:
        if isinstance(value, dict):
            amount = value.get("amount")
            currency = value.get("currency")
        else:
            match = re.fullmatch(
                r"\s*([A-Za-z]{3})\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s*", str(value)
            )
            if not match:
                raise ValueError("currency value must include ISO code and amount")
            currency, amount = match.groups()
        if amount is None or currency is None:
            return NormalizationResult(None, "needs_review", reason="currency or amount missing")
        code = str(currency).upper()
        try:
            get_currency(code)
        except CurrencyDoesNotExist as exc:
            raise ValueError(f"unknown ISO 4217 currency {code}") from exc
        decimal = Decimal(str(amount).replace(",", "").strip())
        return NormalizationResult(
            {"amount": format(decimal, "f"), "currency": code},
            "normalized",
            currency=code,
        )

    def _quantity(self, value: Any, rule: dict[str, Any]) -> NormalizationResult:
        if isinstance(value, dict):
            magnitude = value.get("amount", value.get("value"))
            unit = value.get("unit")
            if magnitude is None:
                raise ValueError("quantity amount missing")
            if not unit:
                return NormalizationResult(
                    {"amount": str(magnitude), "unit": None},
                    "needs_review",
                    reason="quantity unit missing; no unit was inferred",
                )
            quantity = self.units.Quantity(Decimal(str(magnitude)), str(unit))
        else:
            raw = str(value).strip()
            if re.fullmatch(r"[+-]?[0-9][0-9,]*(?:\.[0-9]+)?", raw):
                return NormalizationResult(
                    {"amount": raw.replace(",", ""), "unit": None},
                    "needs_review",
                    reason="quantity unit missing; no unit was inferred",
                )
            quantity = self.units.Quantity(raw)
        target_unit = rule.get("target_unit")
        normalized = quantity.to(target_unit) if target_unit else quantity.to_base_units()
        unit_text = f"{normalized.units:~}"
        return NormalizationResult(
            {"amount": format(Decimal(str(normalized.magnitude)), "f"), "unit": unit_text},
            "normalized",
            unit=unit_text,
        )
