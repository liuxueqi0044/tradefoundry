from datetime import UTC, datetime, timedelta

import pytest

from tradefoundry.ingestion.artifacts import ArtifactIntegrityError
from tradefoundry.ingestion.connectors.memory import MemoryConnector
from tradefoundry.ingestion.contracts import ArtifactCandidate, ConnectorContext, TimeWindow


def test_reference_connector_pages_and_resumes_from_cursor():
    connector = MemoryConnector()
    now = datetime.now(UTC)
    context = ConnectorContext(
        source_id="source-id",
        source_key="fixture",
        source_version=1,
        connector_version=connector.version,
        config={"pages": [[{"id": "a"}], [{"id": "b"}], [{"id": "c"}]]},
        cursor={"page": 1},
        window=TimeWindow(start=now - timedelta(days=1), end=now),
    )
    batches = list(connector.fetch(context))
    assert [batch.records[0].external_id for batch in batches] == ["b", "c"]
    assert [batch.next_cursor for batch in batches] == [{"page": 2}, {"page": 3}]
    assert all(batch.artifacts for batch in batches)


def test_content_addressed_artifact_is_deduplicated_and_integrity_checked(artifact_store):
    candidate = ArtifactCandidate(content=b"immutable", media_type="application/octet-stream")
    first = artifact_store.put(candidate)
    second = artifact_store.put(candidate)
    assert first == second
    assert artifact_store.get(first.sha256) == b"immutable"

    path = artifact_store.root / first.sha256[:2] / first.sha256
    path.write_bytes(b"corrupted")
    with pytest.raises(ArtifactIntegrityError):
        artifact_store.get(first.sha256)
