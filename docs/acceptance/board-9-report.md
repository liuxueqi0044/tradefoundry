# Board 9 acceptance report

- Date: 2026-08-31
- Revision: `a80ce2c0a9ad`
- Result: **accepted for local/MVP sandbox execution, deterministic settlement and governed learning**

## Implemented

S9.1–S9.15 are implemented as twenty-six `execution_*` tables and a provider-neutral `execution`
package. The board adds an ERPNext REST boundary, provider-scoped mappings, durable outbox/attempts,
Board 8-token-bound sales and purchase order commands, immutable ERP snapshots, evidence-backed
milestones and shipment documents, invoice/receivable/payable facts, currency-safe payment
allocations, bank reconciliation and collection signals, quality cases/reserves/events, reconciled
realized contribution P&L, Outcomes, forecast-error records, leakage-safe datasets, out-of-time
challenger evaluations, review-only change proposals and fixed KPI dashboard snapshots.

Board 5 remains the only DealRoute stage authority, Board 8 remains the only policy/approval/token
authority and ERPNext remains the order/inventory/accounting operational ledger. Board nine records
the resulting integration and analytical facts. A live ERP dispatcher, bank feed and automatic model
promotion remain disabled or absent.

## Verification performed

| Check | Result |
|---|---|
| Full S1–S9 regression suite | 229 passed |
| Board-nine core package coverage | 90% excluding thin FastAPI/provider adapter wiring; gate passed |
| Board-nine acceptance scenarios | 21 passed |
| Ruff static checks | Passed |
| SQLite migration | Empty-to-head and board-eight downgrade/re-upgrade passed |
| Alembic schema drift | No new upgrade operations detected |
| Board-nine persistence | 26 tables; migration head `a80ce2c0a9ad` |
| OpenAPI generation | Passed; 208 paths, including 26 board-nine paths |
| ERP adapter contract | Runtime auth headers, success, refusal, timeout, 4xx, 5xx and missing-ID outcomes covered with HTTPX mock transports |
| End-to-end control closure | Real Board 8 approval/token to order, bank reconciliation, Board 5 collection, P&L, Outcome and learning passed |

The only emitted test warning is Starlette's upstream notice that its current `TestClient` import uses
the deprecated `httpx` compatibility path. It does not affect application runtime and should be
addressed with the future FastAPI/Starlette dependency update.

## Risk disposition

- Raw Board 8 tokens and ERP credentials are memory-only. SQL rows retain token IDs, parameter
  hashes, provider references and append-only attempts, not reusable secrets.
- Ambiguous ERP outcomes are quarantined for reconciliation and never blindly replayed.
- A DealRoute cannot receive an order before formal commitment and cannot become `COLLECTED` before
  all sales invoices are allocated to bank-reconciled payments.
- Cross-currency settlement and actual cost accept only a frozen Board 8 conversion; no caller rate
  or normalized amount becomes fact by assertion.
- Accounting detail remains in ERPNext. Realized P&L cites invoices, costs, payments, quality loss and
  an ERP ledger close, and exposes any reconciliation difference.
- Success cannot be self-reported; it derives from route-consistent order, collection and reconciled
  P&L facts. Failure and no-reply labels are first-class learning rows.
- Feature availability, feature creation, observation and outcome cutoffs are all checked. Later
  records cannot be backdated into a historical learning example.
- Challenger results can only open a pending review. They cannot promote themselves or mutate policy,
  templates, ontology or route history.
- No live ERP, bank, buyer, supplier, accounting service, model endpoint or external dashboard was
  contacted.
