import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tradefoundry.ingestion.connectors.base import (
    ConnectorPolicyError,
    ResilientHttpClient,
    validate_fetch_url,
)
from tradefoundry.ingestion.connectors.official import OfficialDataConnector
from tradefoundry.ingestion.contracts import ConnectorContext, TimeWindow


def test_official_json_api_paginates_and_quarantines_missing_ids():
    def handler(request: httpx.Request):
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                json={"results": [{"id": "a"}, {"name": "bad"}], "has_more": True},
                request=request,
            )
        return httpx.Response(
            200, json={"results": [{"id": "b"}], "has_more": False}, request=request
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = OfficialDataConnector(ResilientHttpClient(client))
    now = datetime.now(UTC)
    batches = list(
        connector.fetch(
            ConnectorContext(
                source_id="s",
                source_key="official",
                source_version=1,
                connector_version=connector.version,
                config={
                    "url": "https://example.invalid/api",
                    "format": "json",
                    "id_field": "id",
                    "page_param": "page",
                    "page_start": 1,
                    "max_pages": 3,
                    "has_more_path": "has_more",
                },
                window=TimeWindow(start=now - timedelta(days=1), end=now),
            )
        )
    )
    assert [[row.external_id for row in batch.records] for batch in batches] == [["a"], ["b"]]
    assert batches[0].quarantined[0].reason_code == "missing_external_id"
    assert batches[-1].next_cursor == {"page": 3}


def test_official_csv_bulk_is_parsed():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            content=b"id,title\n1,Pumps\n2,Gloves\n",
            headers={"content-type": "text/csv"},
            request=request,
        )

    connector = OfficialDataConnector(
        ResilientHttpClient(httpx.Client(transport=httpx.MockTransport(handler)))
    )
    now = datetime.now(UTC)
    batch = next(
        iter(
            connector.fetch(
                ConnectorContext(
                    source_id="s",
                    source_key="bulk",
                    source_version=1,
                    connector_version=connector.version,
                    config={"url": "https://example.invalid/file.csv", "format": "auto"},
                    window=TimeWindow(start=now - timedelta(days=1), end=now),
                )
            )
        )
    )
    assert [row.external_id for row in batch.records] == ["1", "2"]


def test_official_zip_and_xml_bulk_are_decoded_without_path_traversal():
    connector = OfficialDataConnector()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("data.json", json.dumps([{"id": "zip-1"}]))
        archive.writestr("../ignored.json", json.dumps([{"id": "unsafe"}]))
        archive.writestr("readme.txt", "ignored")
    artifacts, records, quarantined = connector._decode(
        archive_bytes.getvalue(), "zip", "application/zip"
    )
    assert records == [{"id": "zip-1"}]
    assert [item.metadata["archive_member"] for item in artifacts] == ["data.json"]
    assert quarantined[0].reason_code == "unsupported_archive_member"

    _, xml_records, _ = connector._decode(
        b"<items><item><id>x-1</id><title>Pumps</title></item></items>",
        "xml",
        "application/xml",
    )
    assert xml_records == [{"id": "x-1", "title": "Pumps"}]


def test_http_client_retries_transport_failures():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = ResilientHttpClient(httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.get("https://example.invalid/retry").json() == {"ok": True}
    assert calls == 3


def test_http_client_blocks_private_targets_and_unsafe_redirects():
    with pytest.raises(ConnectorPolicyError):
        validate_fetch_url("http://127.0.0.1/internal")
    with pytest.raises(ConnectorPolicyError):
        validate_fetch_url("http://169.254.169.254/latest/meta-data")

    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            302, headers={"location": "http://127.0.0.1/private"}, request=request
        )

    client = ResilientHttpClient(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ConnectorPolicyError):
        client.get("https://example.invalid/public")
    assert calls == 1
