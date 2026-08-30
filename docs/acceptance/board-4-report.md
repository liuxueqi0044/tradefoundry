# Board 4 acceptance report

- Date: 2026-08-30
- Revision: `744f12c4d0b5`
- Result: **accepted for local/MVP integration**

## Implemented

S4.1–S4.9 are implemented as fourteen `opportunity_*` tables and a provider-neutral domain package.
The board includes evidence-only WorldEvents, multi-label signals, immutable template versions,
explicit/rule/model need candidates, evidence-path participants, preserved route exclusions,
falsifiable hypotheses, three-way audits, issuance commands and replay/operation metrics.

## Verification performed

| Check | Result |
|---|---|
| Full S1–S4 regression suite | 104 passed |
| Board four package coverage | 92.02% (90% gate passed) |
| Board-four acceptance scenarios | 17 passed |
| Ruff static checks | Passed |
| SQLite migration | Empty-to-head and board-three downgrade/re-upgrade passed |
| Alembic schema drift | No new upgrade operations detected |
| PostgreSQL migration compilation | Passed in offline SQL mode |
| OpenAPI generation | Passed; 71 paths |
| HTTP integration | Event, signal, template, need, participant, route, compile, audit and issue flow covered |

## Risk disposition

- No production source, registry, external model, buyer, supplier or communication channel was used.
- The model-proposal contract is provider-neutral and evidence-bounded; no LLM is called by default.
- Initial probability ranges are compiler priors, not calibrated success forecasts or capital scores.
- The auditor is a board-four structural gate, not a substitute for board-eight compliance policy.
- Issuance creates a command only; it creates no Deal Cell, budget, external obligation or message.
- Live PostgreSQL concurrency/load, labelled-corpus quality and production IAM remain deployment gates.
