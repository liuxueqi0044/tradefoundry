# Board 8 acceptance report

- Date: 2026-08-31
- Revision: `e3027c909abe`
- Result: **accepted for local/MVP deterministic finance and governed sandbox execution**

## Implemented

S8.1–S8.16 are implemented as twenty-eight `risk_*` tables and a provider-neutral `controltower`
package. The board adds Decimal Money/FX conversion, versioned cost definitions, landed-cost and
cashflow scenarios, sensitivity and credit assessments, immutable compliance dataset snapshots,
sanctions/ownership screening, export-control and trade-requirement candidates, one versioned policy
authority, communication privacy decisions, ordered approvals, single-use execution tokens, risk
cases/freezes/releases and role-redacted audit exports.

Board seven now consumes board-eight cost, policy and execution-guard adapters. Its legacy local token
flow remains available only when explicitly used by deterministic fixtures; a control token uses the
shared transaction, parameter hash and execution-time freeze check. The live outbound gateway remains
disabled.

The output is a deterministic scenario, candidate compliance assessment or permission record. It is
not legal advice, a TradeAlpha ranking, proof of business success, an order, an invoice or accounting
truth.

## Verification performed

| Check | Result |
|---|---|
| Full S1–S8 regression suite | 208 passed |
| Board-eight core domain coverage | 93% excluding thin FastAPI/board-seven adapter wiring; 90% gate passed |
| Complete board-eight package coverage | 89% including thin routing and adapters |
| Board-eight acceptance scenarios | 29 passed |
| Board-seven regression after control integration | 31 passed |
| Ruff static checks | Passed |
| SQLite migration | Empty-to-head and board-seven downgrade/re-upgrade passed |
| Alembic schema drift | No new upgrade operations detected |
| Board-eight persistence | 28 tables; migration head `e3027c909abe` |
| OpenAPI generation | Passed; 182 paths, including 29 board-eight paths |
| Security checks | No float SQL money columns, raw-token hash export or permissive production fallback found |

The only emitted test warning is Starlette's upstream notice that its current `TestClient` import uses
the deprecated `httpx` compatibility path. It does not affect application runtime or acceptance and
should be addressed with the repository's future FastAPI/Starlette dependency update.

## Risk disposition

- Decimal, py-moneyed, dateutil and Hypothesis cover deterministic arithmetic, currency validation,
  boundary dates and property/golden-case testing without inventing a financial platform.
- RapidFuzz contributes similarity features only. Exact identifiers can block; fuzzy or incomplete
  subjects never auto-clear and non-clear outcomes freeze related external actions.
- Successful dataset versions are immutable and activation is explicit. A failed refresh leaves the
  last active version usable and auditable rather than silently replacing or deleting it.
- Tariff rates, control rules and sanctions entries come only from versioned dataset records. Test
  fixtures are not represented as current official data or legal advice.
- No active policy bundle means deny. Restrictive matches win, an OPA result retains its decision ID
  and revision, and board-seven privacy facts are evaluated through the same authority.
- Approvals bind parameters and enforce order, expiry and separation of duties. Token issuance is
  single-request, raw tokens are never stored, execution rechecks freezes and consumption is once.
- Freeze release requires a different reviewer plus evidence. Operational audit export redacts
  sensitive data and never exports token digests.
- No live buyer, supplier, compliance provider, policy service, message provider, bank, ERP or legal
  decision maker was contacted.
