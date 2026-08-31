from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    aware,
    currency,
    idempotent_row,
    money,
    new_id,
    quantity,
    rate,
    request_fingerprint,
    require_row,
)
from tradefoundry.controltower.contracts import (
    CashflowPlanCreate,
    CostDefinitionCreate,
    CreditAssessmentCreate,
    CreditOverrideCreate,
    FxQuoteCreate,
    LandedCostCreate,
    MoneyAmount,
    MoneyConversionCreate,
    SensitivityCreate,
)
from tradefoundry.controltower.models import (
    CashflowEventRow,
    CashflowPlanRow,
    CostDefinitionRow,
    CreditAssessmentRow,
    CreditOverrideRow,
    FxQuoteRow,
    LandedCostLineRow,
    LandedCostScenarioRow,
    MoneyConversionRow,
    SensitivityRunRow,
)
from tradefoundry.evidence.models import ClaimRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import EntityRow

FINANCE_CALCULATOR_VERSION = "board8-finance-1.0"


@dataclass(frozen=True)
class MoneyValue:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))
        object.__setattr__(self, "currency", currency(self.currency))

    def __add__(self, other: MoneyValue) -> MoneyValue:
        if self.currency != other.currency:
            raise ValueError("different currencies cannot be added without an FX conversion")
        return MoneyValue(self.amount + other.amount, self.currency)

    def __sub__(self, other: MoneyValue) -> MoneyValue:
        if self.currency != other.currency:
            raise ValueError("different currencies cannot be subtracted without an FX conversion")
        return MoneyValue(self.amount - other.amount, self.currency)


class MoneyService:
    def __init__(self, session: Session):
        self.session = session

    def create_quote(self, request: FxQuoteCreate) -> FxQuoteRow:
        request_hash = request_fingerprint({"operation": "risk.fx_quote.create"}, request)
        existing = idempotent_row(self.session, FxQuoteRow, request.idempotency_key, request_hash)
        if existing is not None:
            return existing
        quoted_at = aware(request.quoted_at)
        valid_until = aware(request.valid_until) if request.valid_until else None
        latest = self.session.scalar(
            select(FxQuoteRow)
            .where(FxQuoteRow.quote_key == request.quote_key)
            .order_by(FxQuoteRow.version_no.desc())
        )
        version_no = 1 if latest is None else latest.version_no + 1
        if latest is not None and latest.status == "active":
            latest.status = "superseded"
        snapshot = {
            "base_currency": request.base_currency,
            "quote_currency": request.quote_currency,
            "rate": str(rate(request.rate)),
            "source_name": request.source_name,
            "source_uri": request.source_uri,
            "provider_reference": request.provider_reference,
            "quoted_at": quoted_at.isoformat(),
            "valid_until": valid_until.isoformat() if valid_until else None,
        }
        row = FxQuoteRow(
            id=new_id(),
            quote_key=request.quote_key,
            version_no=version_no,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            base_currency=request.base_currency,
            quote_currency=request.quote_currency,
            rate=rate(request.rate),
            source_name=request.source_name,
            source_uri=request.source_uri,
            provider_reference=request.provider_reference,
            quoted_at=quoted_at,
            valid_until=valid_until,
            content_hash=payload_hash(snapshot),
            status="active",
        )
        self.session.add(row)
        self.session.commit()
        return row

    def convert(self, request: MoneyConversionCreate, *, commit: bool = True) -> MoneyConversionRow:
        request_hash = request_fingerprint({"operation": "risk.money.convert"}, request)
        existing = idempotent_row(
            self.session, MoneyConversionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        converted_at = aware(request.converted_at)
        source_currency = request.money.currency
        target_currency = currency(request.target_currency)
        quote = None
        applied_rate = Decimal("1")
        if source_currency == target_currency:
            if request.fx_quote_id is not None:
                raise ValueError("same-currency conversion must not specify an FX quote")
        else:
            if request.fx_quote_id is None:
                raise ValueError("cross-currency conversion requires an FX quote")
            quote = require_row(self.session, FxQuoteRow, request.fx_quote_id, "FX quote")
            if quote.base_currency != source_currency or quote.quote_currency != target_currency:
                raise ValueError("FX quote direction does not match the requested conversion")
            if aware(quote.quoted_at) > converted_at:
                raise ValueError("FX quote was published after the conversion time")
            if quote.valid_until and aware(quote.valid_until) < converted_at:
                raise ValueError("FX quote is expired at the conversion time")
            applied_rate = Decimal(quote.rate)
        source_amount = money(request.money.amount)
        target_amount = money(source_amount * applied_rate)
        snapshot = {
            "fx_quote_id": quote.id if quote else None,
            "fx_source": quote.source_name if quote else "identity",
            "quoted_at": aware(quote.quoted_at).isoformat() if quote else None,
            "rate": str(rate(applied_rate)),
        }
        row = MoneyConversionRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            source_amount=source_amount,
            source_currency=source_currency,
            target_amount=target_amount,
            target_currency=target_currency,
            fx_quote_id=quote.id if quote else None,
            applied_rate=rate(applied_rate),
            converted_at=converted_at,
            source_snapshot_json=snapshot,
        )
        self.session.add(row)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return row


class CostService:
    def __init__(self, session: Session):
        self.session = session

    def create_definition(self, request: CostDefinitionCreate) -> CostDefinitionRow:
        request_hash = request_fingerprint({"operation": "risk.cost_definition.create"}, request)
        existing = idempotent_row(
            self.session, CostDefinitionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        latest = self.session.scalar(
            select(CostDefinitionRow)
            .where(CostDefinitionRow.component_key == request.component_key)
            .order_by(CostDefinitionRow.version_no.desc())
        )
        if latest is not None and latest.status == "active":
            latest.status = "superseded"
        row = CostDefinitionRow(
            id=new_id(),
            component_key=request.component_key,
            version_no=1 if latest is None else latest.version_no + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            category=request.category,
            allocation_method=request.allocation_method,
            ad_valorem_basis=request.ad_valorem_basis,
            included_incoterms_json=request.included_incoterms,
            description=request.description,
            status="active",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def calculate(self, request: LandedCostCreate) -> LandedCostScenarioRow:
        request_hash = request_fingerprint({"operation": "risk.landed_cost.calculate"}, request)
        existing = idempotent_row(
            self.session, LandedCostScenarioRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        if request.route_id is not None:
            from tradefoundry.deals.models import DealRouteRow

            require_row(self.session, DealRouteRow, request.route_id, "deal route")
        if request.supplier_quote_id is not None:
            from tradefoundry.bilateral.models import SupplierQuoteRow

            require_row(self.session, SupplierQuoteRow, request.supplier_quote_id, "supplier quote")
        component_keys: list[str] = []
        seen: set[tuple[str, str]] = set()
        prepared: list[dict[str, Any]] = []
        goods_conversion = MoneyService(self.session).convert(
            MoneyConversionCreate(
                idempotency_key=f"{request.idempotency_key}:goods",
                money=request.goods,
                target_currency=request.currency,
                fx_quote_id=request.goods_fx_quote_id,
                converted_at=request.calculated_at,
            ),
            commit=False,
        )
        goods_base = Decimal(goods_conversion.target_amount)
        total_low = goods_base
        total_base = goods_base
        total_high = goods_base
        for index, item in enumerate(request.components):
            definition = require_row(
                self.session, CostDefinitionRow, item.definition_id, "cost definition"
            )
            if definition.status != "active":
                raise ValueError(f"cost definition {definition.component_key} is not active")
            dedupe_key = (definition.component_key, item.source_reference)
            if dedupe_key in seen:
                raise ValueError("duplicate cost component source would double count landed cost")
            seen.add(dedupe_key)
            if request.incoterm in definition.included_incoterms_json:
                raise ValueError(
                    f"{definition.component_key} is already included by {request.incoterm}"
                )
            component_keys.append(definition.component_key)
            original_amount: Decimal | None = None
            original_currency: str | None = None
            rate_value: Decimal | None = None
            basis_amount: Decimal | None = None
            fx_quote_id: str | None = None
            if definition.allocation_method == "one_time":
                if item.amount is None:
                    raise ValueError("one_time component requires an amount")
                conversion = MoneyService(self.session).convert(
                    MoneyConversionCreate(
                        idempotency_key=f"{request.idempotency_key}:component:{index}",
                        money=item.amount,
                        target_currency=request.currency,
                        fx_quote_id=item.fx_quote_id,
                        converted_at=request.calculated_at,
                    ),
                    commit=False,
                )
                base = Decimal(conversion.target_amount)
                original_amount = money(item.amount.amount)
                original_currency = item.amount.currency
                fx_quote_id = conversion.fx_quote_id
                explanation = "one-time amount normalized to scenario currency"
            elif definition.allocation_method in {"per_unit", "per_weight"}:
                if item.rate is None or item.rate_currency is None:
                    raise ValueError(
                        f"{definition.allocation_method} component requires rate and rate_currency"
                    )
                units = (
                    Decimal(request.quantity)
                    if definition.allocation_method == "per_unit"
                    else Decimal(request.gross_weight_kg or 0)
                )
                if units <= 0:
                    raise ValueError("per_weight component requires gross_weight_kg")
                original = MoneyAmount(
                    amount=Decimal(item.rate) * units, currency=item.rate_currency
                )
                conversion = MoneyService(self.session).convert(
                    MoneyConversionCreate(
                        idempotency_key=f"{request.idempotency_key}:component:{index}",
                        money=original,
                        target_currency=request.currency,
                        fx_quote_id=item.fx_quote_id,
                        converted_at=request.calculated_at,
                    ),
                    commit=False,
                )
                base = Decimal(conversion.target_amount)
                original_amount = money(original.amount)
                original_currency = original.currency
                rate_value = rate(item.rate)
                fx_quote_id = conversion.fx_quote_id
                explanation = f"{definition.allocation_method} rate multiplied by {units}"
            else:
                if item.rate is None:
                    raise ValueError("ad_valorem component requires a dimensionless rate")
                if item.rate_currency is not None or item.fx_quote_id is not None:
                    raise ValueError("ad_valorem rate must not contain currency or FX quote")
                if definition.ad_valorem_basis != "goods":
                    raise ValueError("only the reviewed goods ad-valorem basis is supported")
                basis_amount = goods_base
                rate_value = rate(item.rate)
                base = money(goods_base * Decimal(item.rate))
                explanation = "ad-valorem rate multiplied by normalized goods value"
            low = money(base * Decimal(item.low_multiplier))
            base = money(base)
            high = money(base * Decimal(item.high_multiplier))
            total_low += low
            total_base += base
            total_high += high
            prepared.append(
                {
                    "definition": definition,
                    "item": item,
                    "original_amount": original_amount,
                    "original_currency": original_currency,
                    "rate_value": rate_value,
                    "basis_amount": basis_amount,
                    "low": low,
                    "base": base,
                    "high": high,
                    "fx_quote_id": fx_quote_id,
                    "explanation": explanation,
                }
            )
        missing = sorted(set(request.required_component_keys) - set(component_keys))
        latest_version = self.session.scalar(
            select(func.max(LandedCostScenarioRow.version_no)).where(
                LandedCostScenarioRow.scenario_key == request.scenario_key
            )
        )
        scenario = LandedCostScenarioRow(
            id=new_id(),
            scenario_key=request.scenario_key,
            version_no=(latest_version or 0) + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            route_id=request.route_id,
            supplier_quote_id=request.supplier_quote_id,
            currency=request.currency,
            quantity=quantity(request.quantity),
            quantity_unit=request.quantity_unit,
            gross_weight_kg=(
                quantity(request.gross_weight_kg) if request.gross_weight_kg else None
            ),
            incoterm=request.incoterm,
            destination_country=request.destination_country,
            goods_amount=money(request.goods.amount),
            goods_currency=request.goods.currency,
            goods_amount_normalized=money(goods_base),
            total_low=money(total_low),
            total_base=money(total_base),
            total_high=money(total_high),
            assumptions_json=request.assumptions,
            missing_inputs_json=missing,
            calculator_version=FINANCE_CALCULATOR_VERSION,
            input_hash=request_hash,
            status="incomplete" if missing else request.status,
            created_by=request.created_by,
        )
        self.session.add(scenario)
        self.session.flush()
        for value in prepared:
            item = value["item"]
            definition = value["definition"]
            self.session.add(
                LandedCostLineRow(
                    id=new_id(),
                    scenario_id=scenario.id,
                    definition_id=definition.id,
                    component_key=definition.component_key,
                    source_reference=item.source_reference,
                    original_amount=value["original_amount"],
                    original_currency=value["original_currency"],
                    rate_value=value["rate_value"],
                    basis_amount=value["basis_amount"],
                    amount_low=value["low"],
                    amount_base=value["base"],
                    amount_high=value["high"],
                    fx_quote_id=value["fx_quote_id"],
                    explanation=value["explanation"],
                )
            )
        self.session.commit()
        return scenario

    def lines(self, scenario_id: str) -> list[LandedCostLineRow]:
        require_row(self.session, LandedCostScenarioRow, scenario_id, "landed cost scenario")
        return list(
            self.session.scalars(
                select(LandedCostLineRow)
                .where(LandedCostLineRow.scenario_id == scenario_id)
                .order_by(LandedCostLineRow.component_key, LandedCostLineRow.source_reference)
            )
        )


class CashflowService:
    def __init__(self, session: Session):
        self.session = session

    def calculate(self, request: CashflowPlanCreate) -> CashflowPlanRow:
        request_hash = request_fingerprint({"operation": "risk.cashflow.calculate"}, request)
        existing = idempotent_row(
            self.session, CashflowPlanRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        if len({item.event_key for item in request.events}) != len(request.events):
            raise ValueError("cashflow event keys must be unique within a plan")
        if request.scenario_id:
            require_row(
                self.session, LandedCostScenarioRow, request.scenario_id, "landed cost scenario"
            )
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(request.events):
            conversion = MoneyService(self.session).convert(
                MoneyConversionCreate(
                    idempotency_key=f"{request.idempotency_key}:event:{item.event_key}",
                    money=item.money,
                    target_currency=request.currency,
                    fx_quote_id=item.fx_quote_id,
                    converted_at=request.calculated_at,
                ),
                commit=False,
            )
            normalized.append(
                {
                    "input": item,
                    "amount": Decimal(conversion.target_amount),
                    "fx_quote_id": conversion.fx_quote_id,
                    "index": index,
                }
            )
        normalized.sort(key=lambda item: (item["input"].occurs_on, item["input"].event_key))
        balance = Decimal("0")
        peak = Decimal("0")
        financing_cost = Decimal("0")
        first_negative = None
        recovered = None
        annual = Decimal(request.annual_financing_rate)
        for index, item in enumerate(normalized):
            event = item["input"]
            signed = item["amount"] if event.direction == "inflow" else -item["amount"]
            balance += signed
            if balance < 0 and first_negative is None:
                first_negative = event.occurs_on
            peak = max(peak, -balance + financing_cost)
            if balance >= 0 and first_negative is not None:
                recovered = event.occurs_on
            if index + 1 < len(normalized):
                days = (normalized[index + 1]["input"].occurs_on - event.occurs_on).days
                if days < 0:
                    raise ValueError("cashflow dates could not be ordered")
                if balance < 0 and days:
                    financing_cost += (-balance) * annual * Decimal(days) / Decimal("365")
                    peak = max(peak, -balance + financing_cost)
        starts_on = normalized[0]["input"].occurs_on
        ends_on = normalized[-1]["input"].occurs_on
        financing_cost = money(financing_cost)
        peak = money(peak)
        working_days = 0
        if first_negative is not None:
            working_days = ((recovered or ends_on) - first_negative).days
        latest_version = self.session.scalar(
            select(func.max(CashflowPlanRow.version_no)).where(
                CashflowPlanRow.plan_key == request.plan_key
            )
        )
        plan = CashflowPlanRow(
            id=new_id(),
            plan_key=request.plan_key,
            version_no=(latest_version or 0) + 1,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            route_id=request.route_id,
            scenario_id=request.scenario_id,
            currency=request.currency,
            annual_financing_rate=rate(annual),
            peak_working_capital=peak,
            financing_cost=financing_cost,
            working_capital_days=working_days,
            starts_on=starts_on,
            ends_on=ends_on,
            assumptions_json=request.assumptions,
            input_hash=request_hash,
            calculator_version=FINANCE_CALCULATOR_VERSION,
            created_by=request.created_by,
        )
        self.session.add(plan)
        self.session.flush()
        for sequence, item in enumerate(normalized, start=1):
            event = item["input"]
            self.session.add(
                CashflowEventRow(
                    id=new_id(),
                    plan_id=plan.id,
                    event_key=event.event_key,
                    event_type=event.event_type,
                    occurs_on=event.occurs_on,
                    direction=event.direction,
                    original_amount=money(event.money.amount),
                    original_currency=event.money.currency,
                    normalized_amount=money(item["amount"]),
                    fx_quote_id=item["fx_quote_id"],
                    generated=False,
                    sequence_no=sequence,
                )
            )
        if financing_cost > 0:
            self.session.add(
                CashflowEventRow(
                    id=new_id(),
                    plan_id=plan.id,
                    event_key="generated:financing_cost",
                    event_type="financing_cost",
                    occurs_on=ends_on,
                    direction="outflow",
                    original_amount=financing_cost,
                    original_currency=request.currency,
                    normalized_amount=financing_cost,
                    fx_quote_id=None,
                    generated=True,
                    sequence_no=len(normalized) + 1,
                )
            )
        self.session.commit()
        return plan

    def events(self, plan_id: str) -> list[CashflowEventRow]:
        require_row(self.session, CashflowPlanRow, plan_id, "cashflow plan")
        return list(
            self.session.scalars(
                select(CashflowEventRow)
                .where(CashflowEventRow.plan_id == plan_id)
                .order_by(CashflowEventRow.sequence_no)
            )
        )


class SensitivityService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _case(
        *,
        label: str,
        sale_price: Decimal,
        cost: Decimal,
        financing_cost: Decimal,
        peak: Decimal,
        variables: dict[str, Any],
    ) -> dict[str, str]:
        revenue_delta = sum(
            (
                Decimal(str(value[label]))
                for value in variables.values()
                if value["affects"] == "revenue"
            ),
            Decimal("0"),
        )
        cost_delta = sum(
            (
                Decimal(str(value[label]))
                for value in variables.values()
                if value["affects"] == "cost"
            ),
            Decimal("0"),
        )
        capital_delta = sum(
            (
                Decimal(str(value[label]))
                for value in variables.values()
                if value["affects"] == "working_capital"
            ),
            Decimal("0"),
        )
        revenue = money(sale_price + revenue_delta)
        total_cost = money(cost + financing_cost + cost_delta)
        return {
            "revenue": str(revenue),
            "total_cost": str(total_cost),
            "profit": str(money(revenue - total_cost)),
            "peak_working_capital": str(money(peak + cost_delta + capital_delta)),
        }

    def calculate(self, request: SensitivityCreate) -> SensitivityRunRow:
        request_hash = request_fingerprint({"operation": "risk.sensitivity.calculate"}, request)
        existing = idempotent_row(
            self.session, SensitivityRunRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        scenario = require_row(
            self.session, LandedCostScenarioRow, request.scenario_id, "landed cost scenario"
        )
        plan = require_row(self.session, CashflowPlanRow, request.cashflow_plan_id, "cashflow plan")
        if request.sale_price.currency != scenario.currency or plan.currency != scenario.currency:
            raise ValueError("sale price, landed cost and cashflow plan currencies must match")
        variables = {
            key: {
                "best": str(value.best),
                "base": str(value.base),
                "worst": str(value.worst),
                "affects": value.affects,
            }
            for key, value in sorted(request.variables.items())
        }
        args = {
            "sale_price": money(request.sale_price.amount),
            "cost": Decimal(scenario.total_base),
            "financing_cost": Decimal(plan.financing_cost),
            "peak": Decimal(plan.peak_working_capital),
            "variables": variables,
        }
        best = self._case(label="best", **args)
        base = self._case(label="base", **args)
        worst = self._case(label="worst", **args)
        sensitivities = []
        for key in variables:
            isolated = {
                variable_key: {
                    **variable_value,
                    "best": (
                        variable_value["base"] if variable_key != key else variable_value["best"]
                    ),
                    "worst": (
                        variable_value["base"] if variable_key != key else variable_value["worst"]
                    ),
                }
                for variable_key, variable_value in variables.items()
            }
            best_one = self._case(label="best", **{**args, "variables": isolated})
            worst_one = self._case(label="worst", **{**args, "variables": isolated})
            sensitivities.append(
                {
                    "variable": key,
                    "profit_best_delta": str(
                        money(Decimal(best_one["profit"]) - Decimal(base["profit"]))
                    ),
                    "profit_worst_delta": str(
                        money(Decimal(worst_one["profit"]) - Decimal(base["profit"]))
                    ),
                    "peak_best_delta": str(
                        money(
                            Decimal(best_one["peak_working_capital"])
                            - Decimal(base["peak_working_capital"])
                        )
                    ),
                    "peak_worst_delta": str(
                        money(
                            Decimal(worst_one["peak_working_capital"])
                            - Decimal(base["peak_working_capital"])
                        )
                    ),
                }
            )
        row = SensitivityRunRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            route_id=request.route_id,
            scenario_id=scenario.id,
            cashflow_plan_id=plan.id,
            currency=scenario.currency,
            variables_json=variables,
            best_case_json=best,
            base_case_json=base,
            worst_case_json=worst,
            sensitivities_json=sensitivities,
            input_hash=request_hash,
            calculator_version=FINANCE_CALCULATOR_VERSION,
        )
        self.session.add(row)
        self.session.commit()
        return row


class CreditService:
    PAYMENT_METHOD_PD = {
        "cash_in_advance": Decimal("0.005"),
        "letter_of_credit": Decimal("0.020"),
        "documents_against_payment": Decimal("0.050"),
        "open_account": Decimal("0.100"),
    }

    def __init__(self, session: Session):
        self.session = session

    def assess(self, request: CreditAssessmentCreate) -> CreditAssessmentRow:
        request_hash = request_fingerprint({"operation": "risk.credit.assess"}, request)
        existing = idempotent_row(
            self.session, CreditAssessmentRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        require_row(self.session, EntityRow, request.entity_id, "entity")
        exposure = money(request.exposure.amount)
        collateral = Decimal(request.collateral_ratio)
        factors: list[str] = []
        if request.completed_trades == 0:
            grade = "UNKNOWN"
            pd = Decimal("0.200")
            credit_limit = money(exposure * collateral)
            status = "unknown"
            factors.append("No completed trade history; conservative collateralized limit applied.")
        else:
            late_ratio = Decimal(request.late_trades) / Decimal(request.completed_trades)
            default_ratio = Decimal(request.defaulted_trades) / Decimal(request.completed_trades)
            method_pd = self.PAYMENT_METHOD_PD.get(request.payment_method, Decimal("0.150"))
            pd = min(
                Decimal("1"),
                max(method_pd, default_ratio, late_ratio * Decimal("0.20")),
            )
            if pd <= Decimal("0.02"):
                grade = "A"
            elif pd <= Decimal("0.05"):
                grade = "B"
            elif pd <= Decimal("0.12"):
                grade = "C"
            else:
                grade = "D"
            credit_limit = money(exposure * max(Decimal("0"), Decimal("1") - pd * 3))
            status = "assessed"
            factors.extend(
                [
                    f"Late-trade ratio={late_ratio:.6f}.",
                    f"Default ratio={default_ratio:.6f}.",
                    f"Payment-method floor={method_pd:.6f}.",
                ]
            )
        lgd = Decimal("0.60") * (Decimal("1") - collateral)
        expected_loss = money(exposure * pd * lgd)
        row = CreditAssessmentRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            entity_id=request.entity_id,
            as_of=aware(request.as_of),
            valid_until=aware(request.as_of) + timedelta(days=request.valid_days),
            payment_method=request.payment_method,
            exposure_amount=exposure,
            currency=request.exposure.currency,
            completed_trades=request.completed_trades,
            late_trades=request.late_trades,
            defaulted_trades=request.defaulted_trades,
            grade=grade,
            probability_of_default=rate(pd),
            loss_given_default=rate(lgd),
            expected_loss=expected_loss,
            credit_limit=credit_limit,
            factors_json=factors,
            status=status,
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def override(self, assessment_id: str, request: CreditOverrideCreate) -> CreditOverrideRow:
        request_hash = request_fingerprint(
            {"operation": "risk.credit.override", "assessment_id": assessment_id}, request
        )
        existing = idempotent_row(
            self.session, CreditOverrideRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        assessment = require_row(
            self.session, CreditAssessmentRow, assessment_id, "credit assessment"
        )
        for claim_id in request.evidence_claim_ids:
            require_row(self.session, ClaimRow, claim_id, "evidence claim")
        row = CreditOverrideRow(
            id=new_id(),
            assessment_id=assessment.id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            previous_grade=assessment.grade,
            new_grade=request.new_grade,
            previous_limit=assessment.credit_limit,
            new_limit=money(request.new_limit),
            approved_by=request.approved_by,
            reason=request.reason,
            evidence_claim_ids_json=request.evidence_claim_ids,
        )
        assessment.grade = request.new_grade
        assessment.credit_limit = money(request.new_limit)
        assessment.status = "overridden"
        self.session.add(row)
        self.session.commit()
        return row
