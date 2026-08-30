# ADR-0007: Bilateral execution as a governed, constraint-coupled record

- Status: accepted
- Date: 2026-08-31
- Decision owner: Sol
- Scope: S7.1–S7.18

## Context

Board seven must validate overseas demand and Chinese supply at the same time. Treating buyer outreach
and supplier sourcing as two independent funnels would hide changes to MOQ, delivery, certification,
payment and product specification. The board also sits immediately before authoritative financial and
compliance controls, so a convenient messaging integration could accidentally create prices,
commitments or contacts that have not passed board eight.

## Decision

The board is a `bilateral` package in the modular monolith with twenty-seven `bilateral_*` tables.
Buyer and supplier profiles reference canonical board-three Entities and evidence Claims. They do not
copy legal identity. Quotes, communications and term versions are durable commercial facts or drafts;
they are not accounting, risk or policy decisions.

The two sides are coupled through immutable qualification and constraint assessments:

```text
evidenced Product/Entity + Deal Route
  -> supplier candidates -> final RFQ -> structured supplier quotes
  -> explicit FX/unit/Incoterm comparison snapshot
  -> buyer contact eligibility -> grounded draft -> interaction
  -> six-part qualification
  -> MOQ/delivery/certification/payment/specification constraint matrix
  -> candidate adjustments + Route reassessment signal
```

The constraint coordinator never changes a Route stage or selects a commercial solution. It records
conflicts and candidate actions such as switching supplier, aggregating buyers, staging delivery,
using trade finance or adjusting a specification. Meeting imports create idempotent board-seven task
proposals; board five remains the owner of executable Actions.

All outbound delivery goes through one gateway. RFQs must pin a final content hash, route-specific
supplier whitelist and approved policy reference. First contacts must pin an allow eligibility
decision, evidence-grounded draft and separate human approval. Raw tokens are returned once and only
their hashes are stored; they bind action, resource, recipient and payload hash, expire and are
single-use. Send time rechecks supplier whitelist or contact suppression. The default gateway is
disabled and the default policy port denies every action, so the board cannot deliver live messages
before board eight is connected.

Buyer quote construction reads an immutable deterministic cost scenario through a Board-8 port. It
cannot accept an arbitrary total from a request. Drafts retain cost status, hash and calculator
version, use an explicit gross-margin formula and remain `pending` approval. There is deliberately no
buyer-quote send path in this board.

## Open-source reuse

- Python's standard `email` and `csv` parsers provide deterministic email and CSV quote adapters.
- Pint performs dimensional unit conversion and rejects incompatible dimensions.
- py-moneyed validates ISO currencies; Decimal performs commercial arithmetic without binary-float
  money errors.
- RapidFuzz proposes candidate Route links for a human queue but never auto-links a fuzzy match.
- phonenumbers normalizes and validates phone contact points.
- Pydantic, SQLAlchemy, Alembic and FastAPI reuse the repository's contracts, persistence and API
  conventions.

No email/CRM SaaS SDK, ERP connector, LLM extraction service, OPA runtime or landed-cost package is
embedded. The standard parsers cover the accepted MVP formats; provider-specific channels, policy
evaluation and deterministic landed cost belong behind explicit adapters in later deployment work.

## Consequences

- A platform display price can remain discovery evidence but can never become a SupplierQuote.
- Missing quote fields remain uncertain and make a quote reviewable or incomparable; conversions
  always retain their source and assumptions.
- New suppliers receive `insufficient_history`, not an artificially excellent zero-event score;
  predicted and actual events remain separate.
- Unsubscribe, complaint, do-not-contact and jurisdiction suppression take precedence over an allow
  policy snapshot, including after token issuance.
- Intent classification is a versioned deterministic baseline. Low confidence creates review state
  and never advances the Deal Route; absence of a reply is not encoded as rejection.
- Negotiation history is append-only and diffed. Internal floor values are hashed rather than copied
  into outward-facing terms; breaches require a later approval.
- Production use still requires board-eight policy, approval, compliance freeze, Money/FX/cost and
  execution-token services, plus a live gateway with provider-level idempotency and delivery controls.
