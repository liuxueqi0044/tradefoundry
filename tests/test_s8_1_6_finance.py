from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tradefoundry.controltower.adapters import Board7CostScenarioAdapter
from tradefoundry.controltower.contracts import (
    CashflowEventInput,
    CashflowPlanCreate,
    CostComponentInput,
    CostDefinitionCreate,
    CreditAssessmentCreate,
    CreditOverrideCreate,
    FxQuoteCreate,
    LandedCostCreate,
    MoneyAmount,
    MoneyConversionCreate,
    SensitivityCreate,
    SensitivityVariable,
)
from tradefoundry.controltower.finance import (
    CashflowService,
    CostService,
    CreditService,
    MoneyService,
    MoneyValue,
    SensitivityService,
)

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _fx(session, *, key="eur-usd", rate="1.10"):
    return MoneyService(session).create_quote(
        FxQuoteCreate(
            quote_key=key,
            idempotency_key=f"fx-{key}-{rate}",
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal(rate),
            source_name="ECB fixture",
            source_uri="https://example.invalid/ecb",
            provider_reference="fixture-2026-08-31",
            quoted_at=NOW - timedelta(hours=1),
            valid_until=NOW + timedelta(hours=1),
        )
    )


@given(
    a=st.decimals(min_value="-100000", max_value="100000", places=4),
    b=st.decimals(min_value="-100000", max_value="100000", places=4),
)
def test_money_addition_is_exact_for_same_currency_and_rejects_mixed_currency(a, b):
    result = MoneyValue(a, "usd") + MoneyValue(b, "USD")
    assert result.amount == MoneyValue(a + b, "USD").amount
    with pytest.raises(ValueError, match="different currencies"):
        MoneyValue(a, "USD") + MoneyValue(b, "EUR")


def test_fx_conversion_records_direction_source_time_and_idempotency(session):
    quote = _fx(session)
    request = MoneyConversionCreate(
        idempotency_key="conversion-1",
        money=MoneyAmount(amount=Decimal("123.45"), currency="EUR"),
        target_currency="USD",
        fx_quote_id=quote.id,
        converted_at=NOW,
    )
    first = MoneyService(session).convert(request)
    replay = MoneyService(session).convert(request)
    assert first.id == replay.id
    assert first.target_amount == Decimal("135.7950")
    assert first.source_snapshot_json["fx_source"] == "ECB fixture"
    with pytest.raises(ValueError, match="direction"):
        MoneyService(session).convert(
            request.model_copy(
                update={
                    "idempotency_key": "conversion-wrong-direction",
                    "money": MoneyAmount(amount=1, currency="USD"),
                    "target_currency": "EUR",
                }
            )
        )


def _definitions(session):
    service = CostService(session)
    packaging = service.create_definition(
        CostDefinitionCreate(
            component_key="packaging",
            idempotency_key="cost-definition-packaging",
            category="packaging",
            allocation_method="one_time",
            description="Export packaging",
            created_by="finance",
        )
    )
    freight = service.create_definition(
        CostDefinitionCreate(
            component_key="ocean_freight",
            idempotency_key="cost-definition-freight",
            category="logistics",
            allocation_method="per_weight",
            included_incoterms=["CIF"],
            description="Ocean freight by kilogram",
            created_by="finance",
        )
    )
    duty = service.create_definition(
        CostDefinitionCreate(
            component_key="customs_duty",
            idempotency_key="cost-definition-duty",
            category="tax",
            allocation_method="ad_valorem",
            ad_valorem_basis="goods",
            description="Dataset-derived customs duty candidate",
            created_by="finance",
        )
    )
    return packaging, freight, duty


def _landed(session, *, incoterm="FOB", required=None, suffix="1"):
    fx = _fx(session)
    packaging, freight, duty = _definitions(session)
    return CostService(session).calculate(
        LandedCostCreate(
            scenario_key=f"landed-golden-{suffix}",
            idempotency_key=f"landed-golden-{suffix}",
            currency="USD",
            quantity=Decimal("10"),
            quantity_unit="piece",
            gross_weight_kg=Decimal("100"),
            incoterm=incoterm,
            destination_country="KE",
            goods=MoneyAmount(amount=Decimal("1000"), currency="EUR"),
            goods_fx_quote_id=fx.id,
            components=[
                CostComponentInput(
                    definition_id=packaging.id,
                    source_reference="supplier:packaging",
                    amount=MoneyAmount(amount=Decimal("100"), currency="USD"),
                    low_multiplier=Decimal("0.9"),
                    high_multiplier=Decimal("1.2"),
                ),
                CostComponentInput(
                    definition_id=freight.id,
                    source_reference="forwarder:freight",
                    rate=Decimal("2"),
                    rate_currency="USD",
                ),
                CostComponentInput(
                    definition_id=duty.id,
                    source_reference="official:tariff",
                    rate=Decimal("0.10"),
                ),
            ],
            required_component_keys=required or ["packaging", "ocean_freight", "customs_duty"],
            assumptions=["Tariff classification is reviewer-confirmed."],
            status="confirmed",
            calculated_at=NOW,
            created_by="finance",
        )
    )


def test_landed_cost_golden_case_is_exact_and_replayable(session):
    scenario = _landed(session)
    assert scenario.goods_amount_normalized == Decimal("1100.0000")
    assert scenario.total_low == Decimal("1500.0000")
    assert scenario.total_base == Decimal("1510.0000")
    assert scenario.total_high == Decimal("1530.0000")
    assert scenario.status == "confirmed"
    adapted = Board7CostScenarioAdapter(session).get(scenario.id)
    assert adapted.total_cost == Decimal("1510.0000")
    assert adapted.snapshot_hash == scenario.input_hash


def test_incoterm_included_component_cannot_be_double_counted(session):
    with pytest.raises(ValueError, match="already included by CIF"):
        _landed(session, incoterm="CIF", suffix="cif")


def test_missing_required_cost_marks_scenario_incomplete(session):
    fx = _fx(session)
    packaging, _, _ = _definitions(session)
    scenario = CostService(session).calculate(
        LandedCostCreate(
            scenario_key="landed-incomplete",
            idempotency_key="landed-incomplete",
            currency="USD",
            quantity=1,
            quantity_unit="piece",
            incoterm="EXW",
            destination_country="KE",
            goods=MoneyAmount(amount=1000, currency="EUR"),
            goods_fx_quote_id=fx.id,
            components=[
                CostComponentInput(
                    definition_id=packaging.id,
                    source_reference="packaging",
                    amount=MoneyAmount(amount=10, currency="USD"),
                )
            ],
            required_component_keys=["packaging", "ocean_freight"],
            calculated_at=NOW,
            created_by="finance",
        )
    )
    assert scenario.status == "incomplete"
    assert scenario.missing_inputs_json == ["ocean_freight"]
    with pytest.raises(ValueError, match="incomplete"):
        Board7CostScenarioAdapter(session).get(scenario.id)


def test_cashflow_peak_capital_days_and_financing_are_deterministic(session):
    plan = CashflowService(session).calculate(
        CashflowPlanCreate(
            plan_key="golden-cashflow",
            idempotency_key="golden-cashflow",
            currency="USD",
            annual_financing_rate=Decimal("0.365"),
            events=[
                CashflowEventInput(
                    event_key="supplier-payment",
                    event_type="supplier_balance",
                    occurs_on=date(2026, 9, 1),
                    direction="outflow",
                    money=MoneyAmount(amount=1000, currency="USD"),
                ),
                CashflowEventInput(
                    event_key="buyer-collection",
                    event_type="buyer_balance",
                    occurs_on=date(2026, 10, 1),
                    direction="inflow",
                    money=MoneyAmount(amount=1500, currency="USD"),
                ),
            ],
            calculated_at=NOW,
            created_by="finance",
        )
    )
    assert plan.peak_working_capital == Decimal("1030.0000")
    assert plan.financing_cost == Decimal("30.0000")
    assert plan.working_capital_days == 30
    assert CashflowService(session).events(plan.id)[-1].generated is True


def test_sensitivity_answers_profit_and_peak_capital_impacts(session):
    scenario = _landed(session, suffix="sensitivity")
    plan = CashflowService(session).calculate(
        CashflowPlanCreate(
            plan_key="sensitivity-cashflow",
            idempotency_key="sensitivity-cashflow",
            currency="USD",
            events=[
                CashflowEventInput(
                    event_key="out",
                    event_type="payment",
                    occurs_on=date(2026, 9, 1),
                    direction="outflow",
                    money=MoneyAmount(amount=1000, currency="USD"),
                )
            ],
            calculated_at=NOW,
            created_by="finance",
        )
    )
    result = SensitivityService(session).calculate(
        SensitivityCreate(
            idempotency_key="sensitivity-1",
            scenario_id=scenario.id,
            cashflow_plan_id=plan.id,
            sale_price=MoneyAmount(amount=2000, currency="USD"),
            variables={
                "freight_shock": SensitivityVariable(
                    best=Decimal("-50"),
                    base=Decimal("0"),
                    worst=Decimal("100"),
                    affects="cost",
                ),
                "delay_capital": SensitivityVariable(
                    best=Decimal("0"),
                    base=Decimal("0"),
                    worst=Decimal("30"),
                    affects="working_capital",
                ),
            },
        )
    )
    assert result.base_case_json["profit"] == "490.0000"
    assert result.worst_case_json["profit"] == "390.0000"
    assert result.worst_case_json["peak_working_capital"] == "1130.0000"


def test_credit_no_history_is_unknown_and_conservative(session, master_entity_factory):
    buyer = master_entity_factory(name="New Buyer")
    assessment = CreditService(session).assess(
        CreditAssessmentCreate(
            idempotency_key="credit-new-buyer",
            entity_id=buyer.id,
            as_of=NOW,
            payment_method="open_account",
            exposure=MoneyAmount(amount=10000, currency="USD"),
            created_by="credit-analyst",
        )
    )
    assert assessment.grade == "UNKNOWN"
    assert assessment.credit_limit == Decimal("0.0000")
    assert assessment.status == "unknown"


def test_credit_override_requires_reason_and_evidence(
    session, master_entity_factory, master_claim_factory
):
    buyer = master_entity_factory(name="Known Buyer")
    assessment = CreditService(session).assess(
        CreditAssessmentCreate(
            idempotency_key="credit-known-buyer",
            entity_id=buyer.id,
            as_of=NOW,
            payment_method="letter_of_credit",
            exposure=MoneyAmount(amount=10000, currency="USD"),
            completed_trades=10,
            late_trades=2,
            created_by="credit-analyst",
        )
    )
    evidence = master_claim_factory(value="Reviewed audited statements", verified=True)
    override = CreditService(session).override(
        assessment.id,
        CreditOverrideCreate(
            idempotency_key="credit-override",
            new_grade="A",
            new_limit=Decimal("9500"),
            approved_by="credit-committee",
            reason="Audited statements and insured exposure support the reviewed limit.",
            evidence_claim_ids=[evidence.id],
        ),
    )
    assert override.previous_grade == "B"
    assert assessment.grade == "A"
    assert assessment.status == "overridden"
