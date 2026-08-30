import pytest

from tradefoundry.master.normalization import MasterDataNormalizer, language_hint


def test_multilingual_names_addresses_and_unicode_normalize_without_losing_raw_text():
    normalizer = MasterDataNormalizer()
    english = normalizer.normalize_name("  ACME Co., LTD.  ")
    chinese = normalizer.normalize_name("上海示例有限公司")
    address = normalizer.normalize_address("12 Main Street, Building 3")

    assert english.raw == "ACME Co., LTD."
    assert english.normalized == "acme"
    assert english.tokens == ["acme"]
    assert chinese.raw == "上海示例有限公司"
    assert chinese.normalized == "上海示例"
    assert chinese.language == "zh"
    assert address.normalized == "12 main st bldg 3"


def test_domain_email_and_phone_use_stable_international_forms():
    normalizer = MasterDataNormalizer()

    assert normalizer.normalize_domain("https://WWW.Example.COM/path") == "example.com"
    assert normalizer.normalize_domain("例子.公司") == "xn--fsqu00a.xn--55qx5d"
    assert normalizer.normalize_email("Sales@Example.COM") == "sales@example.com"
    assert normalizer.normalize_phone("(415) 555-2671", "US") == "+14155552671"

    with pytest.raises(ValueError, match="invalid phone"):
        normalizer.normalize_phone("123", "US")


def test_invalid_contact_values_and_additional_scripts_are_explicit():
    normalizer = MasterDataNormalizer()

    with pytest.raises(ValueError, match="invalid domain"):
        normalizer.normalize_domain("not a domain")
    with pytest.raises(ValueError, match="invalid email"):
        normalizer.normalize_email("missing-at-sign.example")
    with pytest.raises(ValueError, match="invalid phone"):
        normalizer.normalize_phone("definitely-not-a-number", "US")

    assert language_hint("Москва") == "ru"
    assert language_hint("دبي") == "ar"
