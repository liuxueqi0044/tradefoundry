# ADR-0005: Deal execution kernel and durable workflow boundary

- Status: accepted
- Date: 2026-08-30
- Decision owner: Sol
- Scope: S5.1–S5.11

## Context

Board five turns one audited board-four issuance command into reversible commercial experiments. It
must keep multiple routes independent, prevent a status label from becoming unsupported truth,
bound every action by policy and money, survive worker restarts, and retain rejected transitions,
failed attempts and stopped routes for later learning.

The board is not a CRM pipeline. A single mutable stage field, task table and “spent” counter would
lose the evidence, concurrency and audit semantics needed by later scoring, policy and cash boards.

## Decision

Board five is a `deals` package in the modular monolith. Sixteen `deals_*` tables implement the
following append-oriented kernel:

```text
ready DealCellCreateCommand
  -> DealCell (shared boundary, owner, currency, aggregate budget)
  -> DealRoute[] (independent stage, lifecycle, version and budget)
  -> Experiment[] (question, three outcomes, deadline, expiry rule)
  -> Action[] -> ActionAttempt[]
  -> Observation[]
  -> BudgetDecision / Reservation / Spend / Adjustment
  -> timeline + cockpit + next-action queue
```

Route commercial stage and route lifecycle are separate dimensions. Phase changes pass a small
explicit graph and evidence gate, then use an atomic version-checked update. Accepted and rejected
attempts are both appended to `deals_stage_transitions`. Pause, resume, terminate, fork and merge
append lifecycle events without deleting source history.

Forked routes inherit references to observations through `deals_route_evidence_links`; they do not
copy or rewrite the original observation. Their budget, version and subsequent history are
independent. A merge marks the source route as merged and links its evidence to the target while
preserving both histories and ledgers.

## Experiments, actions and observations

Every Experiment defines success, failure and inconclusive conditions, a positive budget, deadline
and explicit expiry behavior. Closing creates one immutable outcome record. Observations retain raw
text, structured interpretation, evidence reference, external reference and a separately labelled
impact proposal. Recording an observation never advances stage or changes a probability.

Actions have dependencies, due time, SLA, estimated cost, policy state and a stable external-effect
key. Queueing reserves budget. Execution atomically claims the action version, appends an attempt,
and records immutable spend on success. A retry reuses the same effect key; an executor must honor
that key at the remote boundary. Compensation appends a new attempt and does not erase the spend or
original receipt.

The shipped application uses `DenyExternalPolicyPort` and `InternalNoopExecutor`. Therefore its
default API can record internal work but cannot perform an external side effect. Board eight must
supply verifiable policy decisions and board seven must supply channel executors before live contact.

## Money and concurrency

Amounts are `Decimal`/`NUMERIC(19,4)` plus a validated ISO currency. Cell, route and experiment
limits form a hierarchy. Reservations and spend are summed from immutable ledgers; both reductions
and increases are checked against committed amounts, sibling allocations and the parent ceiling.
Every adjustment retains approver and reason.

Cell owner changes, experiment start/close, route stage/lifecycle changes, action policy/execution
claims and budget adjustments use expected versions. The database, not the UI or agent, is the
authority for the winning write.

## Workflow and open-source reuse

The MVP uses `DatabaseWorkflowAdapter`: durable jobs, leases, expired-lease reclaim, bounded retries,
wait state and idempotent signals. The `WorkflowAdapter` protocol is the replacement seam.

[Temporal](https://docs.temporal.io/) is the preferred later adapter when deployments require
always-on, multi-worker, long-running orchestration and operational visibility. It is deferred now:
running a Temporal service for a local or intermittently used Codex workflow would add more
operational cost than durability value, while the database adapter already survives process restarts.

[transitions](https://github.com/pytransitions/transitions) was evaluated for the route state
machine. The graph is small; TradeFoundry's difficult logic is evidence gates, rejected-history
retention and optimistic database writes. A generic in-memory state-machine dependency would not
replace those semantics, so the graph remains explicit Python data.

The implementation otherwise reuses Pydantic, SQLAlchemy, Alembic, FastAPI and py-moneyed already
in the repository.

## Consequences and deferred gates

- Later boards receive a durable evidence and execution history, not a mutable CRM summary.
- The local/MVP adapter can be polled by Codex or an operator and does not require 24-hour cloud
  infrastructure.
- Horizontal PostgreSQL contention, executor outbox semantics, remote-provider idempotency,
  production IAM, policy verification and live channel credentials remain deployment gates.
- Board six owns scoring and portfolio allocation. Board seven owns bilateral artifacts/channels.
  Board eight owns policy authority. None may rewrite board-five history.
