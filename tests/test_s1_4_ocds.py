from datetime import UTC, datetime, timedelta

from tradefoundry.ingestion.connectors.ocds import OCDSConnector
from tradefoundry.ingestion.contracts import ConnectorContext, TimeWindow


def test_ocds_record_package_preserves_record_release_and_compiled_relationships():
    payload = {
        "version": "1.1",
        "uri": "https://publisher.invalid/package",
        "records": [
            {
                "ocid": "ocds-test-1",
                "releases": [{"id": "release-1"}, {"id": "release-2"}],
                "compiledRelease": {"ocid": "ocds-test-1", "id": "compiled"},
            },
            {"releases": []},
        ],
    }
    now = datetime.now(UTC)
    batch = next(
        iter(
            OCDSConnector().fetch(
                ConnectorContext(
                    source_id="s",
                    source_key="ocds",
                    source_version=1,
                    connector_version="1.0.0",
                    config={"payload": payload},
                    window=TimeWindow(start=now - timedelta(days=1), end=now),
                )
            )
        )
    )
    assert [row.external_id for row in batch.records] == [
        "record:ocds-test-1",
        "compiled:ocds-test-1",
    ]
    assert batch.records[0].relation["release_ids"] == ["release-1", "release-2"]
    assert batch.records[0].relation["has_compiled_release"] is True
    assert batch.quarantined[0].reason_code == "invalid_ocds_record"
