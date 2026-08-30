# Board 4 operations runbook

## Safe local flow

1. Build a WorldEvent only from verified Claims with original evidence fragments.
2. Classify signals and select an active applicable template.
3. Derive rule candidates and optionally submit a schema-validated model proposal.
4. Discover participants and generate all feasible/excluded routes.
5. Compile hypotheses, inspect fact/inference separation and resolve evidence gaps.
6. Audit at an explicit `as_of` time and pinned policy version.
7. Issue only a passing hypothesis. Treat `ready` as a command for board five, not a created deal.

The API is under `/v1/opportunities`; interactive schemas are available at `/docs`.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
uv run pytest -q tests -k "s4_" --cov=tradefoundry.opportunity --cov-fail-under=90
uv run alembic check
```

## Replay

Pin the WorldEvent fingerprint, template ID/version, compiler version, auditor/policy version and any
model/prompt version. Re-running identical semantic inputs returns the same domain records while
adding a new compiler-run observation with its own correlation ID.

## Incident rules

- Unverified or uncited Claim: stop event construction; repair evidence review upstream.
- Unexpected product inference: deprecate/rollback the template; do not edit old needs.
- False participant: correct/split the world-model relation and re-run discovery with a new version
  if the semantic algorithm changed.
- Expired or prohibited demand: retain REJECT and denied issuance; do not delete the hypothesis.
- Model proposal without event evidence: reject the proposal; never substitute model confidence.
- Issuance consumer unavailable: leave the command `ready`; board four performs no external retry or
  side effect.

## Rollback

Application rollback may continue reading board-four tables. Database rollback to `f4273074a852`
drops all board-four data and is allowed only for disposable/local environments or after an approved
backup/export. Production history should be retained and the application rolled forward.
