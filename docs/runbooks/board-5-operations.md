# Board 5 operations runbook

## Safe local flow

1. Accept only a board-four issuance whose `command_status` is `ready`.
2. Create one Deal Cell with one ISO currency and a bounded aggregate experiment budget.
3. Add feasible issued routes; keep route budgets within the Cell limit.
4. For each route, define an Experiment with three outcomes, budget, deadline and expiry rule.
5. Add Actions with dependencies, due time, SLA and estimated cost.
6. Queue an Action only after its dependency, lifecycle, policy and all three budget guards pass.
7. Execute through an injected executor. Reuse `external_effect_key` on every provider retry.
8. Record raw Observations and structured interpretation; review impact before changing later-board
   probability or allocation.
9. Advance route stage only through its evidence gate. Preserve rejected attempts.
10. Use cockpit/timeline views for operations; use fork/pause/merge instead of rewriting history.

The HTTP boundary is `/v1/deals`; interactive schemas are available at `/docs`. The default API
intentionally denies external actions and has no live channel connector.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
uv run pytest -q tests/test_s5_1_2_deal_aggregate.py tests/test_s5_3_4_state_experiments.py tests/test_s5_5_7_actions_observations_budgets.py tests/test_s5_8_9_queue_lifecycle.py tests/test_s5_10_workflow.py tests/test_s5_11_cockpit_api.py tests/test_s5_edge_cases.py --cov=tradefoundry.deals --cov-fail-under=90
uv run alembic check
```

## Workflow recovery

- A worker claims only a due `ready`/`retry` job and receives a lease token.
- Completion, failure and wait require the current non-expired token.
- If a process dies, another worker can reclaim the `running` job after lease expiry.
- `fail` schedules a bounded retry or marks the job `dead` after `max_attempts`.
- A waiting job becomes ready after the first idempotent signal; a repeated identical signal is safe.
- Inspect `attempts`, `last_error`, `wait_reason`, `lease_expires_at` and persisted signals before
  manual intervention. Do not edit workflow rows directly.

The repository provides the durable adapter and HTTP contracts, not a permanent board-five daemon.
Codex/local polling is appropriate while execution is intermittent. Introduce the Temporal adapter
only when 24-hour orchestration, horizontal workers or long-lived workflows become a real need.

## Incident rules

- Missing/denied PolicyDecision: leave the Action blocked; never override the default deny port.
- Provider timeout after a possible side effect: retry only with the same effect key; reconcile the
  remote receipt before compensation.
- Over-budget Action: retain the denied budget decision; obtain an approved adjustment or shrink
  the experiment. Do not edit reservations or spend.
- Stale version: reload cockpit state and resubmit a new command; do not discard the winning event.
- Unsupported stage: inspect rejection reasons and supply evidence; never set `deals_routes.stage`
  directly.
- Bad Observation interpretation: append a corrected upstream Claim/Observation workflow; retain
  raw text and old record.
- Route no longer viable: pause or terminate with reason. Merge only routes in the same Cell.

## Rollback

Application rollback may continue reading board-five tables. Database downgrade to
`744f12c4d0b5` drops all Deal Cells, route histories, experiments, actions, observations, budgets and
workflow jobs. It is allowed only for disposable/local databases or after an approved backup/export.
Production execution history must be retained and rolled forward.
