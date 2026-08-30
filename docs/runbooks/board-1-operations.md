# Board one operations runbook

## Local start

```powershell
uv sync --extra dev
uv run python -m tradefoundry init-db
uv run uvicorn tradefoundry.api:app --reload
uv run python -m tradefoundry worker --poll-seconds 30
```

Open `http://127.0.0.1:8000/docs` for the control API.

## Production-like start

```powershell
docker compose up --build
docker compose exec api alembic upgrade head
```

## Safe operating order

1. Create a disabled source.
2. Review its access method, commercial-use, retention and redistribution terms.
3. Add a new source version rather than modifying historical metadata.
4. Activate only after the API reports all activation requirements satisfied.
5. Create a fetch run for an explicit time window.
6. Execute the run and review quarantine, change events and quality assessment.
7. Pause or deactivate the source before changing connector configuration.

## Incident rules

- Empty payload, sudden volume drop, duplicate surge or time drift: leave data immutable, pause the source and investigate.
- Field presence drop or repeated failure: acknowledge the persisted alert only after the source contract or connector has been reviewed.
- DOM contract failure: do not silently fall back to guessed selectors.
- Suspected license change: deactivate new acquisition; do not delete prior lawful evidence without a retention decision.
- Repeated connector failure: other sources continue; create a separate retry or replay after diagnosis.
- Artifact hash mismatch: treat as an integrity incident and do not use the record downstream.
