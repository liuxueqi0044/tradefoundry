from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tradefoundry.ingestion.connectors.base import ConnectorPolicyError, ResilientHttpClient
from tradefoundry.ingestion.connectors.web import AuthorizedWebConnector
from tradefoundry.ingestion.contracts import ConnectorContext, TimeWindow


def context(config):
    now = datetime.now(UTC)
    return ConnectorContext(
        source_id="s",
        source_key="web",
        source_version=1,
        connector_version="1.0.0",
        config=config,
        window=TimeWindow(start=now - timedelta(days=1), end=now),
    )


def test_web_is_denied_without_explicit_policy_and_robots_approval():
    connector = AuthorizedWebConnector()
    with pytest.raises(ConnectorPolicyError):
        list(connector.fetch(context({"url": "https://example.invalid"})))


def test_dom_change_is_quarantined_instead_of_silently_parsed():
    def handler(request: httpx.Request):
        return httpx.Response(200, text="<html><title>Changed</title></html>", request=request)

    connector = AuthorizedWebConnector(
        ResilientHttpClient(httpx.Client(transport=httpx.MockTransport(handler)))
    )
    batch = next(
        iter(
            connector.fetch(
                context(
                    {
                        "url": "https://example.invalid/notices",
                        "policy_decision": "allow",
                        "robots_allowed": True,
                        "robots_checked_at": "2026-08-30T00:00:00Z",
                        "permission_basis": "official public notice terms",
                        "required_selectors": [".notice-id"],
                    }
                )
            )
        )
    )
    assert batch.records == []
    assert batch.quarantined[0].reason_code == "dom_contract_failed"


def test_authorized_web_extracts_declared_fields_and_attachments():
    html = """
    <html><title>Tender</title><body><span class='notice-id'>N-42</span>
    <h1>Water pumps</h1><a href='/spec.pdf'>spec</a></body></html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html, request=request)

    connector = AuthorizedWebConnector(
        ResilientHttpClient(httpx.Client(transport=httpx.MockTransport(handler)))
    )
    batch = next(
        iter(
            connector.fetch(
                context(
                    {
                        "url": "https://example.invalid/notices/42",
                        "policy_decision": "allow",
                        "robots_allowed": True,
                        "robots_checked_at": "2026-08-30T00:00:00Z",
                        "permission_basis": "official public notice terms",
                        "required_selectors": [".notice-id", "h1"],
                        "field_selectors": {"id": ".notice-id", "title": "h1"},
                        "id_field": "id",
                        "attachment_selector": "a[href]",
                    }
                )
            )
        )
    )
    assert batch.records[0].external_id == "N-42"
    assert batch.records[0].payload["attachments"] == ["https://example.invalid/spec.pdf"]
