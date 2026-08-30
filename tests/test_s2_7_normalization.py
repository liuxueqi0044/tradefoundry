from tradefoundry.evidence.normalization import ClaimNormalizer


def test_date_currency_decimal_and_quantity_normalization_are_deterministic():
    normalizer = ClaimNormalizer()

    assert normalizer.normalize("2026-10-01", {"type": "date"}).value.startswith("2026-10-01T")
    assert normalizer.normalize("1,234.50", {"type": "decimal"}).value == "1234.50"
    money = normalizer.normalize("USD 1,234.50", {"type": "currency"})
    assert money.value == {"amount": "1234.50", "currency": "USD"}
    quantity = normalizer.normalize("1000 g", {"type": "quantity", "target_unit": "kg"})
    assert quantity.value == {"amount": "1.0", "unit": "kg"}


def test_missing_unit_and_ambiguous_date_are_not_guessed():
    normalizer = ClaimNormalizer()

    quantity = normalizer.normalize("100", {"type": "quantity"})
    date = normalizer.normalize("03/04/2026", {"type": "date"})

    assert quantity.status == "needs_review"
    assert quantity.value["unit"] is None
    assert "no unit was inferred" in quantity.reason
    assert date.status == "needs_review"
    assert date.value is None


def test_invalid_currency_and_quantity_are_blocked():
    normalizer = ClaimNormalizer()

    assert normalizer.normalize("ZZZ 100", {"type": "currency"}).status == "invalid"
    assert normalizer.normalize({"unit": "kg"}, {"type": "quantity"}).status == "invalid"
