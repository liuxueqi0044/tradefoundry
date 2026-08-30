from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

import phonenumbers

LEGAL_SUFFIXES = (
    "company limited",
    "corporation",
    "incorporated",
    "limited",
    "co ltd",
    "corp",
    "ltd",
    "inc",
    "llc",
    "gmbh",
    "sarl",
    "股份有限公司",
    "有限责任公司",
    "有限公司",
)

ADDRESS_REPLACEMENTS = {
    "street": "st",
    "st.": "st",
    "road": "rd",
    "rd.": "rd",
    "avenue": "ave",
    "ave.": "ave",
    "boulevard": "blvd",
    "building": "bldg",
    "floor": "fl",
}


@dataclass(frozen=True)
class NormalizedText:
    raw: str
    normalized: str
    tokens: list[str]
    language: str


class MasterDataNormalizer:
    @staticmethod
    def normalize_name(value: str, language: str | None = None) -> NormalizedText:
        raw = value.strip()
        normalized = _basic(raw)
        for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].strip()
                break
        normalized = _collapse(normalized)
        return NormalizedText(raw, normalized, _tokens(normalized), language or language_hint(raw))

    @staticmethod
    def normalize_address(value: str, language: str | None = None) -> NormalizedText:
        raw = value.strip()
        normalized = _basic(raw)
        words = [ADDRESS_REPLACEMENTS.get(word, word) for word in normalized.split()]
        normalized = " ".join(words)
        return NormalizedText(raw, normalized, _tokens(normalized), language or language_hint(raw))

    @staticmethod
    def normalize_domain(value: str) -> str:
        raw = value.strip()
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
        host = (parsed.hostname or raw).rstrip(".").lower()
        if host.startswith("www."):
            host = host[4:]
        if not host or " " in host:
            raise ValueError("invalid domain")
        try:
            return host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("invalid internationalized domain") from exc

    @classmethod
    def normalize_email(cls, value: str) -> str:
        local, separator, domain = value.strip().partition("@")
        if not separator or not local or not domain or " " in local:
            raise ValueError("invalid email")
        return f"{local.casefold()}@{cls.normalize_domain(domain)}"

    @staticmethod
    def normalize_phone(value: str, region: str | None = None) -> str:
        try:
            parsed = phonenumbers.parse(value, region)
        except phonenumbers.NumberParseException as exc:
            raise ValueError("invalid phone") from exc
        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            raise ValueError("invalid phone")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def language_hint(value: str) -> str:
    for character in value:
        code = ord(character)
        if 0x4E00 <= code <= 0x9FFF:
            return "zh"
        if 0x0400 <= code <= 0x04FF:
            return "ru"
        if 0x0600 <= code <= 0x06FF:
            return "ar"
    return "und-Latn"


def _basic(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return _collapse(normalized)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> list[str]:
    return [token for token in value.split(" ") if token]
