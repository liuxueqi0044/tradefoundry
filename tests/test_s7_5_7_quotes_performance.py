from datetime import UTC, datetime, timedelta

from bilateral_helpers import create_supplier

from tradefoundry.bilateral.contracts import (
    FxRateInput,
    PerformanceEventCreate,
    PerformanceSnapshotRequest,
    QuoteComparisonRequest,
    SupplierQuoteIntake,
)
from tradefoundry.bilateral.quote_parsing import SupplierQuoteParser
from tradefoundry.bilateral.quotes import QuoteComparisonService, SupplierQuoteService
from tradefoundry.bilateral.suppliers import SupplierPerformanceService


def _quote(
    session,
    route_id,
    supplier_id,
    *,
    index,
    intake_format,
    currency,
    unit_price,
    price_unit,
    incoterm,
    specifications,
):
    return SupplierQuoteService(session).intake(
        route_id,
        SupplierQuoteIntake(
            idempotency_key=f"supplier-quote-{index}",
            supplier_profile_id=supplier_id,
            intake_format=intake_format,
            raw_artifact_ref=f"artifact://quote/{index}",
            raw_hash=str(index) * 64,
            received_at=datetime(2026, 9, index, tzinfo=UTC),
            currency=currency,
            unit_price=unit_price,
            price_unit=price_unit,
            moq_quantity="50",
            moq_unit="piece",
            lead_time_days=45,
            tax={"included": False},
            payment_terms="30% deposit",
            incoterm=incoterm,
            valid_until=datetime(2026, 10, 1, tzinfo=UTC),
            specifications=specifications,
        ),
    )


def test_quote_intake_preserves_raw_and_routes_missing_fields_to_review(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    supplier, _, _, _ = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    quote = SupplierQuoteService(session).intake(
        route.id,
        SupplierQuoteIntake(
            idempotency_key="quote-partial-email",
            supplier_profile_id=supplier.id,
            intake_format="email",
            raw_artifact_ref="artifact://raw-email/1",
            raw_hash="a" * 64,
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
            currency="USD",
            total_amount="1000",
            uncertain_fields=["tax"],
        ),
    )

    assert quote.raw_artifact_ref == "artifact://raw-email/1"
    assert quote.raw_hash == "a" * 64
    assert quote.review_status == "needs_review"
    assert set(quote.uncertain_fields_json) >= {
        "tax",
        "moq",
        "lead_time_days",
        "payment_terms",
        "incoterm",
        "valid_until",
    }


def test_email_csv_and_manual_quote_parsers_extract_common_fields_without_guessing():
    parser = SupplierQuoteParser()
    email = parser.parse_email(
        b"From: supplier@example.com\r\nSubject: Quote\r\n\r\n"
        b"Currency: USD\r\nUnit Price: 10.25\r\nPrice Unit: piece\r\n"
        b"MOQ: 100\r\nMOQ Unit: piece\r\nLead Time Days: 30\r\n"
        b"Tax: no\r\nPayment Terms: 30% deposit\r\nIncoterm: FOB\r\n"
        b"Valid Until: 2026-10-01\r\nSpec.material: SS316\r\n"
    )
    spreadsheet = parser.parse_spreadsheet_csv(
        "currency,unit_price,price_unit,moq,moq_unit,lead_time_days,tax,"
        "payment_terms,incoterm,valid_until,spec.material\n"
        "EUR,9.5,piece,50,piece,45,yes,LC at sight,CIF,2026-10-15,SS304\n"
    )
    manual = parser.parse_manual(
        {
            "币种": "CNY",
            "单价": "not-a-number",
            "计价单位": "piece",
            "贸易术语": "unknown",
        }
    )

    assert email.fields["unit_price"] == "10.25"
    assert email.fields["specifications"] == {"material": "SS316"}
    assert email.uncertain_fields == []
    assert spreadsheet.fields["currency"] == "EUR"
    assert spreadsheet.fields["tax"]["included"] is True
    assert spreadsheet.uncertain_fields == []
    assert {"unit_price", "price", "incoterm", "moq", "valid_until"} <= set(manual.uncertain_fields)


def test_three_formats_compare_with_explicit_fx_unit_and_incoterm_assumptions(
    session,
    deal_route_factory,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    _, route = deal_route_factory()
    suppliers = [
        create_supplier(
            session,
            master_entity_factory,
            master_claim_factory,
            product_concept_factory,
            index=index,
        )[0]
        for index in (1, 2, 3)
    ]
    q1 = _quote(
        session,
        route.id,
        suppliers[0].id,
        index=1,
        intake_format="email",
        currency="USD",
        unit_price="10",
        price_unit="kilogram",
        incoterm="CIF",
        specifications={"grade": "A", "certifications": ["ISO 9001"]},
    )
    q2 = _quote(
        session,
        route.id,
        suppliers[1].id,
        index=2,
        intake_format="spreadsheet",
        currency="EUR",
        unit_price="9000",
        price_unit="metric_ton",
        incoterm="FOB",
        specifications={"grade": "B", "certifications": ["ISO 9001"]},
    )
    q3 = SupplierQuoteService(session).intake(
        route.id,
        SupplierQuoteIntake(
            idempotency_key="supplier-quote-3",
            supplier_profile_id=suppliers[2].id,
            intake_format="manual",
            raw_artifact_ref="artifact://quote/3",
            raw_hash="3" * 64,
            received_at=datetime(2026, 9, 3, tzinfo=UTC),
            unit_price="8",
            price_unit="kilogram",
            incoterm="CIF",
            specifications={"grade": "A"},
        ),
    )
    comparison = QuoteComparisonService(session).compare(
        route.id,
        QuoteComparisonRequest(
            idempotency_key="comparison-three-formats",
            quote_ids=[q1.id, q2.id, q3.id],
            target_currency="USD",
            target_unit="metric_ton",
            target_incoterm="CIF",
            fx_rates=[
                FxRateInput(
                    base_currency="EUR",
                    quote_currency="USD",
                    rate="1.10",
                    source_ref="fx:ecb:2026-09-03",
                    as_of=datetime(2026, 9, 3, tzinfo=UTC),
                )
            ],
            incoterm_adjustments={q2.id: "200"},
        ),
    )

    rows = {row["quote_id"]: row for row in comparison.rows_json}
    assert rows[q1.id]["normalized"]["unit_price"] == "10000.0000"
    assert rows[q2.id]["normalized"]["unit_price"] == "10100.0000"
    assert rows[q3.id]["comparable"] is False
    assert q3.id in comparison.incomparable_quote_ids_json
    assert comparison.specification_differences_json["grade"][q1.id] == "A"
    assert comparison.conversion_snapshot_json["fx"]["EUR/USD"]["source_ref"].startswith("fx:ecb")


def test_supplier_performance_separates_prediction_from_actual_and_neutralizes_new_supplier(
    session,
    master_entity_factory,
    master_claim_factory,
    product_concept_factory,
):
    supplier, product, _, evidence = create_supplier(
        session, master_entity_factory, master_claim_factory, product_concept_factory
    )
    service = SupplierPerformanceService(session)
    service.record_event(
        supplier.id,
        PerformanceEventCreate(
            idempotency_key="performance-prediction-only",
            product_concept_id=product.id,
            event_type="delivery",
            predicted={"on_time": True},
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )
    for index, outcome in enumerate(("success", "failure"), start=1):
        service.record_event(
            supplier.id,
            PerformanceEventCreate(
                idempotency_key=f"performance-actual-{index}",
                product_concept_id=product.id,
                event_type="quality",
                actual={"passed": outcome == "success"},
                outcome=outcome,
                evidence_claim_id=evidence.id,
                occurred_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=index),
            ),
        )
    early = service.snapshot(
        supplier.id,
        PerformanceSnapshotRequest(
            idempotency_key="performance-snapshot-early",
            product_concept_id=product.id,
            as_of=datetime(2026, 9, 10, tzinfo=UTC),
            minimum_history=3,
        ),
    )
    assert early.event_count == 3
    assert early.actual_event_count == 2
    assert early.score is None
    assert early.confidence_status == "insufficient_history"

    service.record_event(
        supplier.id,
        PerformanceEventCreate(
            idempotency_key="performance-actual-3",
            product_concept_id=product.id,
            event_type="delivery",
            actual={"on_time": True},
            outcome="success",
            evidence_claim_id=evidence.id,
            occurred_at=datetime(2026, 9, 11, tzinfo=UTC),
        ),
    )
    mature = service.snapshot(
        supplier.id,
        PerformanceSnapshotRequest(
            idempotency_key="performance-snapshot-mature",
            product_concept_id=product.id,
            as_of=datetime(2026, 9, 12, tzinfo=UTC),
            minimum_history=3,
        ),
    )
    assert mature.score == 2 / 3
    assert mature.metrics_json["predicted_only_count"] == 1
