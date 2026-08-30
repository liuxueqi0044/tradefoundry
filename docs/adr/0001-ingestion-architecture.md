# ADR-0001: Board-one ingestion architecture

Status: accepted for implementation  
Owner: Sol  
Date: 2026-08-30

## Decision

Board one is implemented as a Python package inside the TradeFoundry modular monolith. PostgreSQL is the production system of record; SQLite is permitted only for isolated tests and local demonstrations. FastAPI exposes control-plane operations. Connectors implement a versioned Python protocol and emit immutable `ArtifactCandidate` and `SourceRecordCandidate` values. The orchestration service alone persists connector output.

Raw bytes are written to a content-addressed store before a source record is accepted. Record versions are append-only and deduplicated by `(source_id, external_id, payload_hash)`. A current projection may change, but history is never overwritten. Replays create new replay reports and reuse immutable artifacts; they do not rewrite prior observations.

Official APIs and bulk files use HTTPX plus standard parsers. OCDS packages are accepted directly or from Kingfisher Process exports. Authorized HTML uses an explicit allow policy, robots result and DOM contract; it is denied by default. Dagster, dlt, Crawlee and Kingfisher may be added as outer adapters without changing the connector contract.

## Consequences

- The first release remains small enough to run locally and in one cloud worker.
- Open-source collectors can be integrated without making the domain core depend on them.
- Full mid-request pause is not promised; pause prevents subsequent execution and cancellation is checked between batches.
- Source licensing metadata is operational policy, not decorative documentation.

