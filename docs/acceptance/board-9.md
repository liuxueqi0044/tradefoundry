# Board 9 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S9.1 | ERP resources use provider/type-scoped mappings, a durable outbox and append-only attempts; refused connections retry while timeout/5xx/missing-ID results remain ambiguous | `test_s9_1_5_execution.py` |
| S9.2 | Sales and purchase orders require a committed route, verified commitment, ERP party/item mappings and exact Board 8 approval/token binding; the raw token never enters persistence | `test_s9_1_5_execution.py`, `test_s9_board_acceptance.py` |
| S9.3 | ERP events create immutable snapshots; status can progress, commercial conflicts open review and unknown external orders stay `unmapped` | `test_s9_1_5_execution.py` |
| S9.4 | Evidence-backed versioned milestones retain planned/actual time and quantity, partial delivery and lateness; replay is exact and conflicting version reuse fails | `test_s9_1_5_execution.py`, `test_s9_board_acceptance.py` |
| S9.5 | Versioned shipment documents require verified Claim fragments, detect missing/expired/inconsistent sets and redact public storage/sensitive fields | `test_s9_1_5_execution.py`, `test_s9_board_acceptance.py` |
| S9.6 | Sales/purchase invoice facts produce receivable/payable references, normalize only through Board 8 conversions and explain order/invoice discrepancies | `test_s9_6_9_settlement.py` |
| S9.7 | Partial allocations are currency-safe; bank reconciliation is immutable; only fully allocated sales invoices with every contributing payment reconciled publish one durable collection signal | `test_s9_6_9_settlement.py`, `test_s9_board_acceptance.py` |
| S9.8 | Quality cases bind order/batch/supplier/buyer/reporter/evidence, keep append-only events/reserves and require an independent evidenced closure before realizing loss | `test_s9_6_9_settlement.py`, `test_s9_board_acceptance.py` |
| S9.9 | Realized P&L separates revenue from procurement/logistics/financing/FX/commission/warranty/claims, automatically includes payment fees/FX and reconciles to a cited ERP ledger close | `test_s9_6_9_settlement.py`, `test_s9_board_acceptance.py` |
| S9.10 | Success derives price/P&L/cycle from route-consistent immutable facts; failure/stopped/no-reply remain explicit labels with stage/reason and no fabricated success | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |
| S9.11 | Prediction/actual comparison requires real route-bound score, probability, cost and pinned P&L snapshots and rejects inputs created after their cutoff | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |
| S9.12 | Versioned learning datasets copy real FeatureSnapshots only before observation/outcome cutoffs, validate labels and retain failures, no-replies, human intervention and exploration | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |
| S9.13 | Dataset-bound out-of-time evaluation reports Brier/ECE, slices, economic value and safety; missing/insufficient/unsafe evidence makes the challenger ineligible | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |
| S9.14 | Lesson/policy/template/ontology/model changes are evidence-backed `review_pending` proposals and have no automatic application path | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |
| S9.15 | Fixed-version dashboard snapshots aggregate only cited facts at/before `as_of`, use one reporting currency, separate gross sales from contribution P&L and retain validated drilldowns | `test_s9_10_15_learning.py`, `test_s9_board_acceptance.py` |

## Board-level scenario

`test_s9_board_acceptance.py` starts with a quoted DealRoute and verified buyer purchase order. It
passes the route through formal commitment, obtains a real Board 8 policy decision, independent
approval and single-use order token, writes a sandbox ERP sales order, records a late partial
shipment and complete document set, then proves that neither a deposit nor an unreconciled tail
payment can collect the route. After both bank reconciliations it publishes exactly one collection
signal through the Board 5 state machine. Purchase cost, freight, bank fees, realized FX and an
independently closed quality loss reconcile to ERP contribution P&L. The scenario then builds a
successful Outcome and no-reply Outcome, compares pinned forecasts to actuals, creates a
failure-inclusive cutoff-safe dataset, evaluates a challenger, leaves its proposal pending human
review and publishes a fixed-definition dashboard.

## Production gates not claimed by this acceptance

1. `RecordingErpGateway` and deterministic ERP/bank references are fixtures. No live ERPNext or bank
   was contacted and no accounting opinion is expressed.
2. A live Frappe deployment needs a least-privilege service user, runtime secret injection, signed
   webhook verification, provider idempotency lookup and reconciliation runbook testing.
3. ERPNext remains the inventory/accounting ledger. The local tables are integration, audit and
   analytical facts, not a replacement general ledger.
4. The local collection adapter proves the Board 5 gate; production needs bank-statement provenance,
   payment-reconciliation ownership, exception queues and close-period controls.
5. Dashboard figures are fixed deterministic aggregates, not statutory reports. Reporting currency,
   accounting policy and period-close sign-off require finance ownership.
6. Challenger eligibility is not promotion. Sample size, drift, fairness/safety slices, economic
   simulation and human approval remain deployment responsibilities.
7. SQLite proves portable contracts and migration order. PostgreSQL locking, isolation, backup,
   restore, failover and large-volume performance remain operational gates.
