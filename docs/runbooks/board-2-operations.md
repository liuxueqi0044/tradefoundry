# Board 2 operations runbook

## Install and migrate

Base development/API installation:

```powershell
uv sync --extra dev
uv run alembic upgrade head
```

Document worker with PDF, Office and OCR support:

```powershell
uv sync --extra dev --extra documents
```

Pin the lock file in deployment. Do not permit conversion jobs until the migration reports revision `ab23ab0ef044`.

## Processing sequence

1. Submit bytes to `POST /v1/evidence/documents` with a stable `logical_document_id`.
2. Inspect `status`, `security_status`, detected MIME and quarantine reason.
3. Convert accepted content at `POST /v1/evidence/documents/{id}/convert`.
4. Inspect conversion status/errors and fragments before extraction.
5. Create a JSON Schema, then explicitly activate one version.
6. Submit provider output to `/extract`; never bypass this endpoint with direct Claim writes.
7. Route `needs_review` and `conflict` Claims to a reviewer.
8. Downstream consumers read `/claims/{id}/package`, not raw model output.

## Production security gate

`TRADEFOUNDRY_ENVIRONMENT=production` fails file-intake construction when only the development scanner is available. Inject a real scanner that implements `MalwareScanner`, returns `clean`, `malicious` or `error`, and fails closed on timeouts. Record scanner name/signature version in the returned status or intake metadata. Validate it with the EICAR test file without using real malware.

Keep conversion workers isolated from outbound network access unless a specific approved model download or source fetch requires it. Use read-only model caches and CPU/memory/time limits. Never open Office macros or execute embedded HTML/JavaScript.

## Docling promotion

For every Docling/model upgrade:

1. Create a new worker image; never mutate the running image.
2. Run the organization golden corpus: born-digital PDF, scanned PDF, rotated/mixed-language pages, DOCX, PPTX and tables with merged cells.
3. Compare page counts, heading tree, key table cells, failed-page list and citation coordinates.
4. Promote only when tolerances are met. Converter version changes naturally create a new conversion record.

## Schema changes and rollback

Create a new schema version in draft, replay representative extraction outputs, then activate it. Activation deprecates the prior active version under a database uniqueness constraint. Rollback reactivates the earlier version; historical extraction runs continue referencing their original schema IDs.

## Conflict and review operations

- A conflict is expected data, not a worker failure. Do not delete either Claim.
- Verify one Claim or create a corrected Claim with a specific reason and cited fragments.
- Correction creates a new human-authored Claim and marks the original corrected; it does not mutate the original value or raw extraction output.
- Investigate any Claim with no evidence package as a data-integrity incident.

## Incident response

- **Hash mismatch:** stop reads for the object prefix, preserve storage and database snapshots, compare replicas/backups, and treat it as evidence tampering until disproved.
- **Malicious or bomb archive:** keep it quarantined, disable conversion, preserve only according to incident-retention policy, and investigate its source.
- **Conversion regression:** pin the prior worker image; do not rewrite old conversions. Reconvert with a new converter version.
- **Bad schema/model output:** deprecate the schema, preserve failed extraction runs, repair the contract and replay from immutable fragments.
- **Wrong verified Claim:** correct or reject through the review service; never update `value_json` manually.

## Backup and restore

Back up the database and immutable object store as one recovery set. A database restore without matching artifact hashes is incomplete. A quarterly restore drill must sample evidence packages and rehash their referenced objects.
