# ADR-0004: Evidence-bounded opportunity compiler

- Status: accepted
- Date: 2026-08-30
- Decision owner: Sol
- Scope: S4.1–S4.9

## Context

Board four converts verified commercial events into falsifiable trade hypotheses. A classifier alone
is insufficient: the system must distinguish direct demand from inferred need, discover only
evidence-backed participants, preserve excluded routes, record counter-evidence and stop conditions,
and block unsupported or prohibited proposals before board five can create business state.

## Decision

Board four is an `opportunity` package inside the modular monolith. It consumes verified Claims and
public world-model concepts and emits a versioned Deal Cell create command. It does not create a
Deal Cell itself.

```text
verified Claim + Entity/Product/Relation
  -> immutable WorldEvent fact snapshot
  -> deterministic multi-label Signal
  -> active versioned OpportunityTemplate
  -> explicit / template / LLM ProductNeed candidates
  -> evidence-path Participant candidates
  -> feasible and excluded Deal Route candidates
  -> falsifiable TradeHypothesis
  -> append-only HypothesisAudit
  -> ready or denied DealCellCreateCommand
```

Fourteen `opportunity_*` tables store events and evidence links, signals, immutable template
versions and state changes, product needs, participants, routes, hypotheses, audits, issuance
commands and compiler runs.

## Facts and inference

`TradeHypothesis` stores `fact_assertions_json` and `inference_assertions_json` separately. Explicit
product Claims stay facts. Template and model-derived needs remain candidates with confidence,
uncertainty and a derivation chain. Statements use “may create a need” for inferred products.

The LLM entry point accepts only a schema-validated proposal with model name, prompt version,
concise reasoning summary, uncertainty and verified Claim IDs already belonging to the WorldEvent.
It stores no private chain-of-thought and cannot mark a need explicit or verified.

## Determinism and replay

- WorldEvents deduplicate on a canonical snapshot of facts, canonical entities, products and time.
- Signal, need, participant and route implementations carry fixed versions.
- Route candidates include an input hash; changed participants produce a new preserved snapshot.
- Hypotheses deduplicate on event, template, need, participants, routes, evidence gaps and compiler
  version, excluding transient correlation IDs.
- Every compiler invocation records duration, result counts, error type and correlation ID.

## Audit and issuance

The auditor is append-only and has three outcomes:

- `pass`: evidence, currency, route and policy gates passed;
- `needs_data`: the proposal remains useful but buyer, route or counter-evidence is unresolved;
- `reject`: evidence is missing/unverified, a number has no cited Claim, demand expired, verified
  counter-evidence is dispositive, or a hard/template prohibition applies.

Only the latest `pass` can emit a `deal-cell-create-command-v1`. Denied attempts persist their
reason. The command contains pinned template, compiler, auditor and policy versions and no budget,
score or external action.

## Open-source reuse and deferral

The implementation reuses Pydantic, SQLAlchemy, Alembic, JSON columns and FastAPI already present in
the repository. No new rule-engine dependency is introduced. The template predicates are small,
bounded and core to TradeFoundry's evidence semantics; a generic engine would add another language
without replacing the domain compiler.

[JSON Logic](https://github.com/orgs/json-logic/repositories) remains an option if portable rule
authoring becomes a measured need. [Open Policy Agent](https://www.openpolicyagent.org/docs) is a
general-purpose policy engine and is deferred to board eight's shared policy/authorization boundary;
board four consumes explicit policy flags but does not become the system policy authority.

## Consequences and deferred gates

The deterministic baseline is intentionally conservative and may return `needs_data` often. Real
recall/precision evaluation needs a labelled event/hypothesis corpus. LLM provider integration,
retrieval of similar cases, production OPA integration, Deal Cell state, scoring, budgets and all
external communication remain downstream or deployment gates.
