# TradeFoundry repository rules

- Preserve the evidence-first, event-driven, modular-monolith architecture.
- Do not write connector output directly into downstream business schemas.
- Raw artifacts and historical source versions are append-only.
- Every external record requires a stable source key, external ID, observed time and payload hash.
- Connector runs must be idempotent and replayable.
- Never activate a production source without recorded license, owner, schedule, access method and SLA.
- Web acquisition is denied by default and requires explicit policy plus robots approval.
- Connector configuration stores secret references only; inline tokens, passwords and API keys are forbidden.
- Connector HTTP clients must reject localhost, private/link-local IPs and unsafe redirect targets.
- Changes to contracts, state machines, data deletion, licensing policy or external side effects require Sol review.
- Use Decimal for money in later boards; never use floating point for financial values.
- Run `ruff check .` and `pytest` before declaring a work package complete.
