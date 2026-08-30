# Board 6 operations runbook

## Safe shadow flow

1. Seed or review the active feature registry. A definition change creates a new version.
2. Materialize a Route feature snapshot with an explicit aware `as_of`; inspect source availability,
   context, completeness and registry hash.
3. Apply an active deterministic scoring policy. Treat hard veto separately from numerical score.
4. Estimate stage probabilities with named priors. Small samples must retain wide intervals.
5. Simulate same-currency cashflows with a fixed seed and explicit valuation date.
6. Review route continuation value with sunk cost separated from future avoidable cost.
7. Value candidate Actions using post-action scenarios and legal/reputation cost. Do not recommend
   zero or negative VOI.
8. Assess the whole candidate set against the active risk-limit version, then allocate. A high score
   remains `restricted` when any hard exposure or budget limit would break.
9. Run historical replay using only snapshots available at cutoff and labels that became available
   later. Compare alpha with simple, seeded-random and manual baselines.
10. Monitor Brier, ECE, prediction drift and country/product slices. On degradation, use the rule
    baseline recommendation.
11. Promote only immutable versions with passing out-of-time and safety evidence. Rollback is a new
    event, never a rewrite.
12. Enable exploration only after the outcome threshold and keep it at or below ten percent; exclude
    uncleared, high and critical risk candidates.

The HTTP boundary is `/v1/tradealpha`; interactive schemas are available at `/docs`. Outputs are
recommendations. Operators must not translate an allocation row into an external Action without the
board-five action boundary and later board-eight policy approval.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
uv run coverage run --omit="*/tradealpha/api.py" --source=tradefoundry.tradealpha -m pytest -q tests/test_s6_1_2_features_scoring.py tests/test_s6_3_6_probability_valuation.py tests/test_s6_7_9_portfolio.py tests/test_s6_10_13_governance.py tests/test_s6_api.py
uv run coverage report --omit="*/tradealpha/api.py" --fail-under=90
uv run alembic check
```

For service-domain coverage, omit the thin `tradealpha/api.py` router when measuring the 90% gate;
the HTTP contract has its own smoke test and OpenAPI generation check.

## Incident rules

- Snapshot source later than `as_of`: reject and inspect source business/recorded time; never edit the
  snapshot row.
- Unexpected score: inspect factor contributions, imputation assumptions, hard rules and registry
  hash before changing weights.
- Narrow interval on little data: stop use and review priors/sample construction.
- Calibration degraded: fall back to the deterministic rule baseline and open a model-risk review.
- Limit violation: retain the restricted result; change exposure or create an approved new limit-set
  version. Never bypass the allocator.
- Mixed currencies: stop and obtain a versioned FX valuation design; never assume parity.
- Replayed ranking changed: verify the exact feature registry, policy version, cutoff and seed.
- Exploration over cap or high-risk selection: disable exploration and treat it as a severity-one
  decision-control defect.

## Rollback

Application rollback may continue reading board-six tables. Database downgrade to `8be19a6c3d21`
drops all TradeAlpha snapshots, simulations, valuations, allocations, backtests, calibration reports,
model governance and exploration history. It is allowed only for disposable/local databases or
after an approved backup/export. Production decision history must be retained and rolled forward.
