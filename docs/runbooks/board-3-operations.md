# Board 3 operations runbook

## Install and migrate

```powershell
uv sync --extra dev
uv run alembic upgrade head
```

Install the optional batch-linkage environment only on evaluation workers:

```powershell
uv sync --extra dev --extra resolution
```

The expected schema revision is `f4273074a852`.

## Safe entity intake

1. Create entities only from validated or verified Claims.
2. Supply a stable `entity_key`; reuse with a different request hash is rejected.
3. Preserve each source spelling as an Alias and each source field as an Attribute.
4. Add identifiers through the identifier service, not by direct table insert.
5. Treat the canonical profile as a projection. Do not copy it into another mutable “golden” table.

## Strong-identifier incidents

An exact compatible strong identifier normally creates an automatic merge command. If it contradicts a human distinct constraint, entity type or freeze, both roots become frozen and an identity conflict is created.

Reviewers must choose one action:

- `keep_distinct`: preserve separate roots, retain a distinct constraint and mark the identifier conflict as confirmed.
- `merge`: explicitly override the earlier distinct assumption, unfreeze compatible roots and create a human merge command.

Never clear `frozen_reason`, edit canonical pointers or delete conflicts manually.

## Probabilistic matching

The default API creates candidates only; `auto_merge=false`. Every result includes model version, snapshot hash, probability, features and applicable threshold. A reviewer may merge or reject. Rejection creates a distinct constraint.

Before enabling auto-merge in any environment:

1. Freeze a labelled, time-separated corpus including hard negatives and subsidiaries.
2. Measure precision/recall by entity type and risk tier plus calibration error.
3. Compare the optional Splink challenger and the online baseline.
4. Set a precision-first threshold; high-value buyers and people require stricter values.
5. Record model/config version and rollback criteria.

## Merge, undo and split

- Merge only canonical roots of the same type.
- Repeating an idempotency key with a different payload is rejected.
- Undo the original merge when it remains directly reversible; otherwise issue an explicit split command.
- After any split, sample canonical profile, identifier search and affected relation paths. Source Claims and edge IDs must remain unchanged.

## Products and specifications

- Product codes begin as `candidate`, regardless of classifier confidence.
- Only a named reviewer with a reason may verify or reject a mapping.
- Publish a new immutable specification key/version rather than overwriting requirements.
- Inspect diff output for unit conversions and original wording before downstream use.

## Relations and graph queries

Every Relation requires a validated Claim; a `verified` Relation requires a verified Claim. Set validity intervals when the source has dates. Query consumers must retain confidence and review state rather than treating every returned edge as certain.

One-to-three-hop traversal is intentionally bounded. At higher volume, add PostgreSQL candidate blocking, pg_trgm indexes and recursive-CTE benchmarks before considering a graph projection.

## Privacy and recovery

Names, personal identifiers, emails and telephones may be PII. Do not place raw profiles in logs or model prompts without policy authorization. Back up the master and evidence tables together: a master-data restore without its Claims is incomplete. A restore drill must verify canonical profiles, merge history, distinct constraints and relation evidence.
