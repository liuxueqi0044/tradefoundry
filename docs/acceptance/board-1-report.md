# Board one Sol acceptance report

Date: 2026-08-30  
Decision: **ACCEPTED for local/MVP integration**  
Production source activation: **not authorized by this report**

## Scope decision

The first board, Global Sensors and Source Governance, is implemented for S1.1–S1.9. The accepted boundary ends at immutable artifacts, versioned source records, quarantine items, change events, data-quality alerts and replay reports. Claim extraction and all downstream commercial inference remain outside this board.

## Module decisions

| ID | Result | Accepted capability |
|---|---|---|
| S1.1 | PASS | Append-only source versions; activation requires owner, access method, schedule, SLA and reviewed commercial/retention terms; governed web adds robots check and permission basis |
| S1.2 | PASS | Versioned connector contract, cursor, bounded batch, retry, rate limit, timeout path, immutable artifact and record candidates |
| S1.3 | PASS | Official JSON/CSV/XML/ZIP, nested IDs, time windows, pagination, attachment inventory, quarantine and checkpoint continuation |
| S1.4 | PASS | OCDS release package, record package, compiled release, relation preservation and invalid-shape quarantine; accepts Kingfisher Process-style output |
| S1.5 | PASS | Deny-by-default web adapter, permission/robots gates, declared DOM contract, attachment discovery and DOM-failure quarantine |
| S1.6 | PASS | Schedule calculation, persistent worker, start/pause/resume/cancel, full rerun, checkpoint retry, priority and same-window concurrency guard |
| S1.7 | PASS | Added, updated, revoked, deadline and attachment events; repeated historical transitions remain representable |
| S1.8 | PASS | Health score, persistent alerts, empty feed, record/field drop, duplicate surge, time drift and repeated failure; one source failure does not stop another |
| S1.9 | PASS | Fixed-window full replay, connector-version check, original observation preservation and added/missing/unchanged diff |

## Verification evidence

| Check | Result |
|---|---|
| Automated tests | 27 passed |
| Ingestion package coverage | 90.39%; enforced floor 85% |
| Ruff static checks | Passed, zero findings |
| API smoke | Health, source creation, activation and list passed |
| CLI smoke | Deterministic two-page demo succeeded: 2 batches, 2 records, 2 artifacts, 2 changes, 0 quarantine |
| SQLite migration | Upgrade passed; `alembic check` found no drift; downgrade passed |
| PostgreSQL migration compilation | Transactional SQL generated: 13 tables, 22 indexes, COMMIT present |
| Performance regression | Full suite approximately 6 seconds on this machine; lazy HTTP client removed a prior 12–14 second per-run certificate-loading delay |

## Security decisions included

- Connector configuration rejects inline API keys, tokens, passwords and client secrets; only `credential_ref` is permitted.
- Direct localhost, loopback, link-local, private and other non-public IP targets are rejected.
- Redirect targets are revalidated and redirect count is bounded.
- Raw bytes are content-addressed and verified again when read.
- Compose publishes database and API ports on `127.0.0.1` only.
- A source is disabled whenever a new source version is created and must pass activation again.
- Only one current version per source/external record can exist at the database level.

## Open-source reuse

The implementation composes FastAPI, Pydantic, SQLAlchemy, Alembic, HTTPX, Tenacity, Beautiful Soup, croniter, PostgreSQL/SQLite and uv. OCDS input is compatible with direct packages and Kingfisher Process output. Dagster, dlt and Crawlee are intentionally kept as optional outer adapters; the core connector contract does not duplicate their orchestration roles or depend on their deployment.

## Remaining production gates

These are deployment/operations gates, not missing S1.1–S1.9 domain code:

1. A live PostgreSQL container was not executed on this host because Docker Desktop/WSL stalled during startup. The daemon was stopped after the attempt. SQLite migration round-trip and PostgreSQL static migration compilation passed; an actual PostgreSQL integration run remains mandatory before production deployment.
2. No real source is activated. A human must verify each source's terms, commercial use, retention, redistribution, robots decision, owner and SLA.
3. Authenticated sources require a secrets-provider implementation that resolves `credential_ref`; credentials must never be copied into source configuration.
4. The API must remain local or behind authenticated reverse proxy/OIDC. The current Compose binding is deliberately local-only.
5. Persistent quality alerts are implemented; email, Slack or pager delivery is not configured.
6. Direct private IP and redirects are blocked, but production still needs network egress policy and DNS controls against rebinding.
7. FastAPI's current TestClient emits one upstream Starlette deprecation warning. It does not affect runtime behavior and should be removed when the upstream replacement stabilizes.

## Sol conclusion

Board one may be consumed by board two through its immutable artifact and record contracts. It may also run locally with deterministic fixtures and approved public sources. It must not yet be exposed publicly or used for unattended production acquisition until the remaining production gates above are signed off.

