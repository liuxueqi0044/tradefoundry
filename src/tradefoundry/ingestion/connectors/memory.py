from collections.abc import Iterable

from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.contracts import (
    ArtifactCandidate,
    ConnectorBatch,
    ConnectorContext,
    SourceRecordCandidate,
)
from tradefoundry.ingestion.hashing import canonical_json_bytes


class MemoryConnector(BaseConnector):
    """Deterministic reference connector used by contract tests and demos."""

    name = "memory"
    version = "1.0.0"

    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        pages = context.config.get("pages", [])
        start = int((context.cursor or {}).get("page", 0))
        for index in range(start, len(pages)):
            rows = pages[index]
            artifact = ArtifactCandidate(
                content=canonical_json_bytes(rows),
                media_type="application/json",
                source_url=f"memory://{context.source_key}/{index}",
                metadata={"page": index},
            )
            records = [
                SourceRecordCandidate(external_id=str(row["id"]), payload=row, artifact_index=0)
                for row in rows
            ]
            yield ConnectorBatch(
                artifacts=[artifact],
                records=records,
                next_cursor={"page": index + 1},
                metrics={"page": index, "records": len(records)},
            )
