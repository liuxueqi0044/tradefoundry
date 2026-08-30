# ADR-0006: TradeAlpha as an append-only shadow decision engine

- Status: accepted
- Date: 2026-08-31
- Decision owner: Sol
- Scope: S6.1–S6.13

## Context

Board six must rank scarce attention and capital without turning uncertain commercial evidence into
false precision. It consumes board-five state and outcomes, but it must not rewrite those records or
perform an Action. Sparse outcomes, temporal leakage, sunk-cost bias, hidden hard limits and premature
online learning are the principal risks.

## Decision

TradeAlpha remains inside the modular monolith behind its own `tradealpha` package and eighteen
`alpha_*` append-oriented tables. Its layers are ordered and independently auditable:

```text
as-of feature snapshot
  -> independent hard veto + deterministic baseline score
  -> conditional probability chain + cashflow distribution
  -> route continuation value + action VOI
  -> portfolio exposure assessment
  -> constrained allocation recommendation
  -> calibration / replay / model governance / controlled exploration
```

Every derived record pins an idempotency key, input references, version or calculator name, seed and
business time. Feature materialization reconstructs route stage, lifecycle and completed action
attempts as of the requested time. Mutable current board-five summaries are not used as historical
outcomes. Historical replay rejects outcomes visible at cutoff.

The initial scoring model is a versioned deterministic rule baseline. The probability model is a
five-stage conditional Beta chain. Exact slices are used only when enough same-registry historical
snapshots exist; otherwise the estimator visibly falls back through broader cohorts. Cashflow uses
seeded triangular Monte Carlo and reports distributions rather than a single asserted number.

Route continuation value separates future avoidable cost from sunk spend. Action priority is net
value of information after cash, attention and legal/reputation risk. Negative VOI is not
recommended. Portfolio limits are independent hard constraints across total budget, country, buyer,
product, currency, unsecured credit and correlation group. The allocator cannot override them.

## Open-source reuse

- NumPy supplies deterministic random generators, simulation and quantiles.
- SciPy supplies Beta distribution posterior quantiles.
- Pydantic, SQLAlchemy, Alembic, FastAPI, py-moneyed and Decimal reuse the repository's contracts,
  persistence, API and money conventions.
- Brier score and ECE remain direct, reviewed formulas; scikit-learn would add a large dependency for
  two small calculations.
- MLflow is the preferred later external registry when artifact serving, remote tracking or a model
  operations team justifies a service. The current immutable registry captures the needed local
  governance semantics now.
- PyMC, MABWiser and mixed-integer optimization are deferred until representative Outcomes, an
  evaluated objective and operational need exist.

## Consequences

- The board is usable immediately for local shadow ranking and replay without a 24-hour model
  service.
- “No Outcome” means rule ranking, not learned intelligence. Insufficient samples and degradation are
  explicit states.
- Results are reproducible but only as good as pinned priors, cashflow inputs, risk limits and source
  availability semantics.
- Board seven may consume recommendations to prepare bilateral artifacts, but cannot treat them as
  policy approval. Board eight remains the authority for financial/compliance permission. Board nine
  remains the authority for actual Outcome and accounting truth.

