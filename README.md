# TradeFoundry

TradeFoundry is an evidence-first operating system for discovering and executing global trade
opportunities. The repository currently contains all nine completed local/MVP modular-monolith boards:

1. **Global sensors and source governance**
2. **Evidence vault and document intelligence**
3. **Commercial world model**
4. **Opportunity compiler**
5. **Deal Cell and route experiments**
6. **TradeAlpha and portfolio decision support**
7. **Governed buyer/supplier bilateral execution**
8. **Financial risk, compliance and approval control tower**
9. **Authorized execution, settlement and governed learning closure**

## Implemented scope

| ID | Capability | Entry point |
|---|---|---|
| S1.1 | Versioned source registry and production activation gate | `ingestion/registry.py` |
| S1.2 | Connector SDK with cursor, batch, artifact and record contracts | `ingestion/connectors/base.py` |
| S1.3 | Official API and JSON/CSV/XML/ZIP bulk connector | `ingestion/connectors/official.py` |
| S1.4 | OCDS release/record/compiled-release adapter | `ingestion/connectors/ocds.py` |
| S1.5 | Deny-by-default authorized web adapter and DOM contract | `ingestion/connectors/web.py` |
| S1.6 | Scheduling, run states, retry/rerun and batch execution | `ingestion/runs.py`, `scheduler.py` |
| S1.7 | Added, updated, revoked, deadline and attachment changes | `ingestion/changes.py` |
| S1.8 | Configurable health score and anomaly detection | `ingestion/quality.py` |
| S1.9 | Backfill/replay with immutable observations and diff report | `ingestion/replay.py` |
| S2.1–S2.2 | Versioned evidence vault and security-gated file intake | `evidence/intake.py` |
| S2.3–S2.4 | Docling/text conversion and page/bbox/table-cell fragments | `evidence/conversion.py` |
| S2.5 | Versioned JSON Schema extraction registry | `evidence/schemas.py` |
| S2.6–S2.8 | Evidence-grounded Claims, normalization, conflicts and time travel | `evidence/claims.py`, `normalization.py`, `conflicts.py` |
| S2.9 | Append-only human review and correction trail | `evidence/review.py` |
| S2.10 | Evidence package and citation API | `evidence/retrieval.py`, `evidence/api.py` |
| S3.1–S3.2 | Unified entity model and multilingual normalization | `master/entities.py`, `master/normalization.py` |
| S3.3–S3.5 | Strong/probabilistic identity resolution, reversible merge/split and golden profiles | `master/identifiers.py`, `matching.py`, `resolution.py` |
| S3.6–S3.7 | Product ontology, classification candidates and comparable specifications | `master/products.py`, `specifications.py` |
| S3.8–S3.9 | Evidence-backed temporal relation graph and master-data query API | `master/relations.py`, `queries.py`, `api.py` |
| S4.1–S4.3 | Evidence-only WorldEvents, multi-label signals and immutable opportunity templates | `opportunity/events.py`, `signals.py`, `templates.py` |
| S4.4–S4.6 | Explicit/rule/model product needs, evidence-path participants and preserved route exclusions | `opportunity/needs.py`, `participants.py`, `routes.py` |
| S4.7–S4.9 | Falsifiable hypotheses, PASS/NEEDS_DATA/REJECT audit and Deal Cell issuance command | `opportunity/compiler.py`, `auditor.py`, `issuance.py` |
| S5.1–S5.3 | Idempotent Deal Cells, independent Deal Routes and append-only phase-gated route state | `deals/aggregates.py`, `state_machine.py` |
| S5.4–S5.7 | Three-outcome experiments, retryable action ledger, raw observations and hierarchical budgets | `deals/experiments.py`, `actions.py`, `observations.py`, `budgets.py` |
| S5.8–S5.11 | Explainable next actions, route fork/merge lifecycle, durable workflow adapter and cockpit timeline | `deals/queue.py`, `lifecycle.py`, `workflow.py`, `cockpit.py` |
| S6.1–S6.3 | Temporal feature registry, deterministic scoring and conditional probability chain | `tradealpha/features.py`, `scoring.py`, `probability.py` |
| S6.4–S6.9 | Cashflow/route/action valuation, portfolio limits, constrained allocation and explanation | `tradealpha/valuation.py`, `risk.py`, `allocation.py`, `explanation.py` |
| S6.10–S6.13 | Leakage-safe replay, calibration, model registry and capped exploration | `tradealpha/analytics.py`, `registry.py`, `exploration.py` |
| S7.1–S7.2 | Evidence-backed supplier profiles, capabilities, discovery pool and governed whitelist | `bilateral/suppliers.py` |
| S7.3–S7.4 | Versioned Chinese RFQs, explicit gaps, final-version pinning and one-time approved sending | `bilateral/rfq.py`, `outbound.py` |
| S7.5–S7.7 | Email/CSV/manual quote adapters, structured intake, explicit comparability and product-level performance | `bilateral/quote_parsing.py`, `quotes.py`, `suppliers.py` |
| S7.8–S7.11 | Evidence-backed buyer/contact CRM, suppression-first eligibility, grounded drafts and first-contact approval | `bilateral/crm.py`, `messaging.py`, `outbound.py` |
| S7.12–S7.14 | Raw-preserving interaction intake, conservative thread linking, intent review and six-part qualification | `bilateral/messaging.py` |
| S7.15–S7.18 | Bilateral constraint matrix, Board-8 cost seam, immutable negotiation terms and meeting action proposals | `bilateral/coordination.py` |
| S8.1–S8.3 | Decimal Money/FX, versioned cost definitions and deterministic landed-cost scenarios | `controltower/finance.py` |
| S8.4–S8.6 | Dated cashflow/working capital, sensitivity and conservative credit assessment | `controltower/finance.py` |
| S8.7–S8.8 | Immutable compliance dataset versions, explained screening, ownership propagation and automatic freezes | `controltower/datasets.py`, `screening.py` |
| S8.9–S8.11 | Effective-dated export/trade candidates and unified communication privacy decisions | `controltower/trade_rules.py`, `privacy.py` |
| S8.12–S8.14 | Versioned default-deny policy, ordered approvals and bound single-use execution tokens | `controltower/policy.py`, `governance.py` |
| S8.15–S8.16 | Risk cases, independent evidence-backed freeze release and role-redacted audit export | `controltower/governance.py`, `audit.py` |
| S9.1–S9.3 | ERPNext mappings/outbox, Board-8-token-bound orders and immutable ERP reconciliation snapshots | `execution/erp.py`, `orders.py` |
| S9.4–S9.5 | Evidence-backed fulfillment milestones and version-consistent redacted shipment documents | `execution/fulfillment.py`, `documents.py` |
| S9.6–S9.7 | Invoice/receivable/payable facts, currency-safe allocations, immutable bank reconciliation and collection signals | `execution/settlement.py` |
| S9.8–S9.9 | Independently reviewed quality cases and ERP-reconciled realized contribution P&L | `execution/quality.py`, `pnl.py` |
| S9.10–S9.12 | Fact-derived Outcomes, pinned prediction errors and cutoff-safe failure-inclusive learning datasets | `execution/learning.py` |
| S9.13–S9.15 | Out-of-time challenger evaluation, review-only change proposals and fixed-definition KPI snapshots | `execution/evaluation.py`, `reviews.py`, `dashboard.py` |

## Quick start

```powershell
uv sync --extra dev
uv run python -m tradefoundry init-db
uv run python -m tradefoundry demo
uv run uvicorn tradefoundry.api:app --reload
```

The module form avoids Windows application-control policies that sometimes block generated
console-script launchers. The API documentation is then available at
`http://127.0.0.1:8000/docs`.

Run one due-work cycle or keep a worker polling:

```powershell
uv run python -m tradefoundry worker-once
uv run python -m tradefoundry worker --poll-seconds 30
```

For PostgreSQL:

```powershell
docker compose up -d db
$env:TRADEFOUNDRY_DATABASE_URL='postgresql+psycopg://tradefoundry:tradefoundry@localhost:5432/tradefoundry'
uv run alembic upgrade head
uv run uvicorn tradefoundry.api:app
```

`docker compose up --build` also provides a persistent worker service. Apply migrations before
allowing API or worker traffic in a production deployment.

PDF, Office and OCR conversion runs in a document worker with the optional Docling stack:

```powershell
uv sync --extra dev --extra documents
```

The base install still converts HTML, Markdown, JSON, CSV and plain text. Production file intake
must inject a real malware scanner; setting `TRADEFOUNDRY_ENVIRONMENT=production` deliberately
refuses the development-only signature scanner.

For large-batch probabilistic-linkage experiments, install the optional Splink stack:

```powershell
uv sync --extra dev --extra resolution
```

The online world-model path uses RapidFuzz features and an explainable versioned logistic baseline.
Probabilistic auto-merge is disabled by default; exact strong identifiers and explicit reviewed
commands are the normal merge paths until a deployment-specific model is calibrated.

## Verification

```powershell
uv run ruff check .
uv run pytest
```

Tests are organized by the S1.1–S1.9, S2.1–S2.10, S3.1–S3.9, S4.1–S4.9,
S5.1–S5.11, S6.1–S6.13, S7.1–S7.18, S8.1–S8.16 and S9.1–S9.15 acceptance identifiers. They use deterministic
fixtures, mock HTTP transports, an in-memory outbound gateway and contract-level model fixtures; no
live website, buyer, supplier, communication channel, financial service, ERP, bank or external model is
contacted during validation.

## Boundary with later boards

Board one emits immutable raw artifacts, versioned source records, quarantine items, change events and
quality assessments. Board two turns authorized artifacts into versioned, cited Claims. Board three
resolves those Claims into reversible canonical entities, products, specifications and relations.
Board four compiles verified events into audited hypotheses and versioned Deal Cell creation
commands. Board five turns only a passing command into durable Deal Cell/Route experiments, actions,
observations and budget ledgers. Board six adds append-only shadow scores, distributions, valuations
and constrained portfolio recommendations. Board seven prepares and records governed bilateral
commercial artifacts, but defaults to no live outbound delivery. Board eight provides deterministic
cost/cash scenarios and the sole current policy, compliance freeze, approval and production-token
authority. Its assessments are not legal advice and its scenarios are not accounting truth. Board
nine maps approved commitments to ERP-native order intents, reconciles invoices/payments without
copying the ERP general ledger, derives realized P&L and Outcomes, and builds cutoff-safe governed
learning records. A local passing test does not configure a live ERP/bank integration or authorize
automatic model promotion.

Before starting another board, review the short [architecture checkpoint](docs/architecture-checkpoint.md).
See [ADR-0001](docs/adr/0001-ingestion-architecture.md),
[ADR-0002](docs/adr/0002-evidence-and-claims.md),
[ADR-0003](docs/adr/0003-commercial-world-model.md),
[ADR-0004](docs/adr/0004-opportunity-compiler.md),
[ADR-0005](docs/adr/0005-deal-execution-kernel.md),
[ADR-0006](docs/adr/0006-tradealpha-decision-engine.md),
[ADR-0007](docs/adr/0007-governed-bilateral-execution.md),
[ADR-0008](docs/adr/0008-finance-compliance-control-tower.md),
[ADR-0009](docs/adr/0009-execution-settlement-learning-closure.md), and the board nine
[operations runbook](docs/runbooks/board-9-operations.md).
