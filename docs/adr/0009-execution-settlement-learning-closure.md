# ADR-0009: Execution, settlement and learning closure

- Status: accepted
- Date: 2026-08-31
- Decision owner: Sol
- Scope: S9.1–S9.15

## Context

Board nine closes the gap between an approved commercial commitment and a learning record. Board
seven owns quotes and negotiated commercial facts; board eight owns current policy, freezes,
approval and single-use execution authority. Neither is an order ledger, bank reconciliation,
realized P&L ledger or model-training label.

The closure must avoid two attractive but unsafe shortcuts. First, TradeFoundry must not reproduce
ERPNext inventory or general-ledger behavior in local tables. Second, a CRM stage, payment promise or
unreconciled gateway response must not be called cash collection. Forecasts and post-outcome facts
must also remain distinguishable so later learning cannot leak future information into historical
features.

## Decision

Board nine is the `execution` package in the modular monolith with twenty-six `execution_*` tables.
It uses three connected ledgers:

```text
verified commitment + Board 8 decision/approval/token
  -> durable outbox -> ERPNext order effect -> immutable ERP snapshots
  -> fulfillment milestones + versioned shipment-document facts

ERP invoices + ERP/bank payment facts
  -> currency-pinned allocations -> bank reconciliation
  -> durable CollectionSignal -> Board 5 COMMITTED -> COLLECTED gate
  -> realized contribution P&L reconciled to an ERP ledger reference

route/order/collection/P&L/fulfillment/quality facts
  -> immutable Outcome -> prediction/actual comparison
  -> cutoff-safe failure-inclusive dataset -> out-of-time challenger evaluation
  -> review-only proposal + fixed-definition operating dashboard
```

ERPNext remains the operational source of truth for customers, suppliers, items, sales/purchase
orders, inventory, invoices, payments and accounting entries. TradeFoundry stores mappings,
authorized commands, outbox attempts, immutable reconciliation snapshots and analytical facts; it
does not duplicate the general ledger. ERP external IDs are unique within provider and resource
type, not globally. A live master-data effect needs an explicitly authorized operator boundary, and
the default API only queues the intent. Order creation additionally requires a committed DealRoute,
a verified commitment Claim, ERP party/item mappings, and the exact Board 8 token binding. Fixed
numeric precision is canonicalized before token hashing so the database round-trip cannot change
the authorized parameters.

The outbox is durable and each attempt is append-only. Connection refusal is retryable; a timeout,
5xx response or response without an external identifier is ambiguous and is not blindly retried.
The raw execution token and runtime ERP credentials are never persisted. Successful order effects
consume the Board 8 token exactly once.

ERP order events form immutable snapshots. Commercial-field disagreement opens a review issue;
ordinary ERP status progression does not. An event without a local mapping is `unmapped`, never
silently reconciled. Milestones and shipment documents require verified Claim/fragment evidence.
Their `(shipment, type/key, version)` identity is replay-safe and a reused version with different
facts is rejected. Sensitive document locations are redacted at the public API boundary.

Invoices create receivable/payable references but do not copy accounting entries. Cross-currency
amounts accept only a frozen Board 8 `MoneyConversion`; caller-supplied rates or normalized totals
are rejected. Allocations compare one normalized currency and cannot exceed the normalized payment.
Bank reconciliation is immutable and requires the originating bank reference, ERP reconciliation
reference and evidence. A CollectionSignal is published only when all non-void sales invoices are
fully allocated and every contributing payment is bank-reconciled. Board five then independently
checks the `COMMITTED -> COLLECTED` transition; Board nine never edits the route directly.

Quality cases bind order, batch, supplier, buyer, reporter and evidence. Reserves/events are
append-only, the reporter cannot independently close the case, and realized loss enters P&L only
after evidenced closure. Realized contribution P&L separately attributes revenue, procurement,
logistics, financing, FX, commission, warranty and claim/refund cost. Payment fees and realized FX
are included automatically, and a snapshot is `reconciled` only when its contribution matches the
pinned ERP ledger total and reference.

An Outcome does not trust caller-reported price, profit or cycle length. A successful label requires
one route-consistent order, published collection signal and reconciled P&L, with optional fulfillment
and quality facts validated against the same cutoff. Failure, stopped and no-reply labels are
retained with a failed stage or reason. Prediction comparisons require real immutable TradeAlpha
score/probability snapshots, a Board 8 cost scenario and the exact P&L snapshot pinned by the
Outcome. Prediction inputs must have existed before the prediction cutoff; actual P&L may occur
later but not after the outcome cutoff.

Learning datasets copy a real FeatureSnapshot only when `as_of`, maximum source availability and
record creation all precede the observation cutoff, which itself must precede the Outcome. Labels
must agree with the referenced Outcome, preserve human intervention/exploration markers and include
at least one failure or no-reply row. Challenger evaluation binds deterministic dataset order,
labels and a strict out-of-time window. Missing economic or safety evaluation fails eligibility, as
does an insufficient critical slice. Eligibility only creates a review proposal; no service can
automatically promote a model or change policy, templates or ontology. Dashboard snapshots aggregate
validated invoice, P&L, cashflow and Outcome references in one reporting currency and keep gross
sales separate from contribution profit.

## Open-source reuse

- [Frappe REST](https://docs.frappe.io/framework/user/en/api/rest) is the ERPNext integration
  boundary. Runtime token headers are injected in memory; the repository does not fork or copy the
  GPL ERP core.
- [Frappe webhooks](https://docs.frappe.io/framework/user/en/guides/integration/webhooks) define the
  production event seam, including its HMAC signature. The local/MVP endpoint remains behind a
  trusted integration boundary and does not claim a configured webhook secret.
- ERPNext's documented [Payment Entry](https://docs.frappe.io/erpnext/payment-entry),
  [Payment Reconciliation](https://docs.frappe.io/erpnext/payment-reconciliation) and
  [Payment Ledger](https://docs.frappe.io/erpnext/payment_ledger) semantics are referenced instead
  of reimplementing accounting behavior.
- HTTPX supplies deterministic REST transports and mock adapters; SQLAlchemy/Alembic supply the
  transactional outbox, mappings and portable migration; Pydantic/FastAPI supply versioned contracts
  and the HTTP boundary; Python `Decimal` supplies exact monetary comparison.
- No Kafka, Celery, Airflow, feature store or new model registry is added. The existing database,
  worker pattern, TradeAlpha snapshots and review workflow are sufficient for the MVP. Metabase may
  read the fixed dashboard snapshots later but is not embedded as another source of KPI truth.

## Consequences

- ERPNext availability can delay execution without losing intent or creating a second uncontrolled
  write.
- `COLLECTED` now means reconciled cash evidence, not an optimistic CRM stage.
- Forecasts, actuals and training rows remain separately replayable and temporally auditable.
- The final board completes the local/MVP functional loop, but it does not claim a configured live
  ERP, bank feed, webhook secret, production PostgreSQL concurrency exercise, accounting sign-off or
  automatic model promotion.
- Production must configure ERP service-user least privilege, secret management, signed webhooks,
  bank/ERP reconciliation ownership, backups, observability and human review SLAs before live use.
