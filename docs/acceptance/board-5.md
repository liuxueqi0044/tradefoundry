# Board 5 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S5.1 | Only one ready board-four issuance creates an idempotent Deal Cell with pinned hypothesis boundaries, owner, version, currency and aggregate budget | `test_s5_1_2_deal_aggregate.py` |
| S5.2 | One Cell holds multiple independent Deal Routes; each has its own roles, stage, lifecycle, version and budget, and aggregate allocations cannot exceed the Cell | `test_s5_1_2_deal_aggregate.py` |
| S5.3 | The explicit route graph rejects illegal or ungated advances, retains every rejection, snapshots supporting evidence and atomically checks route version | `test_s5_3_4_state_experiments.py`, `test_s5_edge_cases.py` |
| S5.4 | Experiments require a budget, deadline, expiry rule and success/failure/inconclusive definitions; start/close are versioned and one outcome is appended | `test_s5_3_4_state_experiments.py` |
| S5.5 | Actions have stable effect keys, dependencies, retries, attempts and compensation; a successful repeat does not repeat execution or spend | `test_s5_5_7_actions_observations_budgets.py` |
| S5.6 | Observations retain raw and structured forms plus evidence/impact metadata and cannot directly mutate route stage, version or probability | `test_s5_5_7_actions_observations_budgets.py`, `test_s5_edge_cases.py` |
| S5.7 | Cell/route/experiment guards reserve before execution, append immutable spend, enforce parent/sibling ceilings and record approved limit changes | `test_s5_5_7_actions_observations_budgets.py`, `test_s5_edge_cases.py` |
| S5.8 | The next-action queue orders by executability and deadline and explains dependency, policy, lifecycle and budget blockers while retaining SLA | `test_s5_8_9_queue_lifecycle.py` |
| S5.9 | Pause/resume/terminate/fork/merge are versioned and idempotent; forks share evidence references but own budgets, and merges preserve source history | `test_s5_8_9_queue_lifecycle.py` |
| S5.10 | The database workflow adapter persists jobs, leases, retries, wait state and signals; an expired lease is reclaimed after a simulated process restart | `test_s5_10_workflow.py` |
| S5.11 | Route/Cell cockpit and timeline expose budgets, experiments, observations, next actions, blockers and append-only events through HTTP contracts | `test_s5_11_cockpit_api.py` |

## Production gates not claimed by this acceptance

1. A production board-eight `PolicyDecisionPort`, sanctions/export-control decisions and IAM.
2. Live board-seven email, portal, RFQ or messaging executors with provider-side idempotency tests.
3. PostgreSQL concurrency/load testing at target route/action volume and transaction isolation review.
4. A continuously running worker fleet or Temporal deployment; the current adapter is DB-backed MVP.
5. Board-six calibrated scoring and capital allocation using representative outcomes.
6. Production alerting, secrets, backups, point-in-time recovery and disaster-recovery drills.
