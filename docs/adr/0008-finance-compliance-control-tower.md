# ADR-0008: Finance and compliance as the sole execution authority

- Status: accepted
- Date: 2026-08-31
- Decision owner: Sol
- Scope: S8.1–S8.16

## Context

Board eight must provide numbers that can be replayed and controls that cannot be bypassed. It sits
between commercial preparation and irreversible execution: board seven creates RFQs, drafts,
contacts and negotiated terms, while board nine will create orders, shipments and cash records. A
calculator hidden in a quote workflow or policy rules copied into several services would make the
same action receive different answers and would leave no reliable audit trail.

The design must also distinguish a mechanical screening result from legal advice. Names, product
codes, ownership and jurisdiction data are often incomplete or ambiguous. Unknown data therefore
cannot silently become a clear compliance result or a generous credit decision.

## Decision

The board is a `controltower` package in the modular monolith with twenty-eight `risk_*` tables. It
owns immutable financial scenarios, versioned compliance datasets and assessments, policy
decisions, approvals, action tokens, freezes, cases and audit exports. It does not own canonical
company identity, Deal Route ranking, communication facts, orders or accounting truth.

The execution boundary is one pipeline:

```text
versioned facts and assumptions
  -> deterministic cost / cash / compliance assessment
  -> current versioned policy decision
  -> ordered approval chain with separation of duties
  -> short-lived, parameter-bound execution token
  -> execution-time freeze and parameter recheck
  -> one external effect and an auditable consumption record
```

Money uses `Decimal`; currencies cannot be added directly and every conversion pins pair,
direction, rate, source and quote time. Cost definitions state their allocation basis and Incoterm
inclusion so an included component cannot be counted twice. Landed-cost, cashflow and sensitivity
outputs retain their inputs, missing assumptions, calculator version and deterministic hash. Credit
without history is `unknown` with a conservative limit; an override is a separate, evidenced and
expiring record.

Compliance sources are immutable dataset versions. Activating a successful version retires the
previous active version; a failed synchronization records the failure without deleting that usable
version. Screening explains exact identifier and fuzzy-name fields. Exact identifiers block,
possible or incomplete matches require review, and every non-clear result opens a case and freeze.
Ownership risk propagates to the screened subject. Export-control, tariff, certification and trade-
remedy assessments only return candidates from an effective-dated dataset; missing end use and
ambiguous codes remain review states.

All authorization rules are evaluated through one `PolicyEngine`. The embedded deterministic
backend is the local/MVP reference and defaults to deny when no rule matches; execution adapters deny
when no active bundle is configured. An OPA REST adapter preserves the external decision ID and
policy revision for production deployment. Communication privacy passes board-seven contact,
lawful-basis, retention and active suppression facts into that same engine instead of maintaining
another allow list.

Approval requests bind an action, subject set, parameter hash, policy decision and ordered steps.
They support one or multiple reviewers, tiered thresholds, expiry and separation of duties. A raw
execution token is returned only at issuance; only its digest is stored. It is issued once per
approved request, expires, binds action/resource/parameters, is reserved idempotently around the
external call and is consumed once. The board-seven outbound adapter uses this token in the same
database transaction as its outbound record and rechecks current freezes at execution time.

Freeze release is append-only and requires an independent reviewer, reason and evidence. Audit
exports connect financial assumptions, screening, policy, approval, token, freeze and evidence
references. Operational exports redact sensitive fields; full auditor exports require an explicit
role. Token digests are never exported.

## Open-source reuse

- Python `Decimal`, py-moneyed and python-dateutil provide deterministic amounts, ISO currency
  validation and date arithmetic.
- RapidFuzz provides transparent name-similarity features; it never makes the final legal decision.
- Hypothesis exercises money arithmetic as properties in addition to hand-calculated golden cases.
- OPA is supported behind its REST decision API rather than embedded as an undeclared process.
- The OpenSanctions/yente data model and matching approach informed the provider boundary, but no
  dataset, service or license entitlement is bundled. Production sources must be licensed and
  approved separately.
- Pydantic, SQLAlchemy, Alembic, FastAPI and HTTPX reuse the repository's existing contracts,
  persistence, HTTP and adapter conventions.

No tax rate, sanctions name, export rule or legal conclusion is embedded in a prompt. The repository
contains provider-neutral mechanics and deterministic fixtures, not a claim that its test data is a
current official compliance source.

## Consequences

- Missing policy configuration denies execution instead of falling back to a permissive board-seven
  stub.
- A high TradeAlpha score cannot override a freeze, credit boundary, policy deny or approval chain.
- Approval permits exactly one bound action; it is not evidence that the action succeeded or that a
  transaction is profitable.
- Weak identity data remains reviewable and blocked from external effects until resolved.
- Production must operate dataset freshness, OPA bundle/decision logs, independent reviews, secrets,
  a live outbound provider and legal ownership of jurisdiction-specific rules.
- Board nine can create an order or other external commitment only through this control boundary and
  must retain the policy, approval and token references with the resulting execution fact.
