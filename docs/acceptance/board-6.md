# Board 6 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S6.1 | A versioned registry materializes immutable, as-of feature snapshots with registry hash, source references, context and completeness; future records are excluded | `test_s6_1_2_features_scoring.py` |
| S6.2 | A deterministic weighted baseline retains factors, assumptions, gaps and sensitivity while independent hard rules can veto any score | `test_s6_1_2_features_scoring.py` |
| S6.3 | The five-stage conditional Beta chain reports priors, observations and credible intervals; small samples remain visibly uncertain and seeded replay is exact | `test_s6_3_6_probability_valuation.py` |
| S6.4 | Seeded triangular Monte Carlo discounts revenue, variable cost and credit/quality/compliance loss into mean, quantiles and best/worst cases | `test_s6_3_6_probability_valuation.py` |
| S6.5 | Route value separates sunk cost, future avoidable cost, attention and peak working capital; sunk cost does not alter the continuation decision | `test_s6_3_6_probability_valuation.py` |
| S6.6 | Action valuation subtracts cash, attention and legal/reputation risk from expected post-action value; non-positive VOI is never recommended | `test_s6_3_6_probability_valuation.py` |
| S6.7 | Portfolio assessment reports explicit country, buyer, product, currency, unsecured-credit and correlation violations plus marginal headroom | `test_s6_7_9_portfolio.py` |
| S6.8 | Deterministic allocation orders by score/action ID, never exceeds portfolio or exposure limits, and marks otherwise attractive candidates as restricted | `test_s6_7_9_portfolio.py` |
| S6.9 | The explanation contract exposes factor contributions, hard constraints, assumptions, gaps, sensitivities and valuable next evidence | `test_s6_1_2_features_scoring.py` |
| S6.10 | Historical replay accepts only pinned as-of snapshots and outcomes unavailable at cutoff, then compares alpha, stage, random and manual rankings | `test_s6_10_13_governance.py` |
| S6.11 | Brier score and ECE are reported overall and by country/product; insufficient data is labelled and degradation forces a rule-baseline recommendation | `test_s6_10_13_governance.py` |
| S6.12 | Immutable model versions require a strict out-of-time split; champion/rollback events pass sample, Brier, ECE and safety criteria | `test_s6_10_13_governance.py` |
| S6.13 | Controlled exploration is disabled below the outcome threshold, excludes uncleared/high-risk candidates and cannot exceed ten percent of budget | `test_s6_10_13_governance.py` |

## Production gates not claimed by this acceptance

1. The current model registry stores artifact URIs and governance events but does not serve arbitrary
   trained artifacts; only verified rule-baseline execution is enabled.
2. Priors, calibration thresholds, loss distributions and risk limits require representative
   board-nine Outcomes and a named financial/risk owner before production use.
3. Allocation is a transparent deterministic greedy baseline, not a claim of globally optimal
   mixed-integer portfolio construction.
4. Exploration is seeded uniform selection inside hard boundaries, not a contextual-bandit claim.
5. Cross-currency allocation requires a versioned FX source and valuation time; this board rejects
   mixed currencies rather than silently converting them.
6. PostgreSQL load/concurrency testing, monitoring, backups, IAM and independent model-risk review
   remain deployment gates.

