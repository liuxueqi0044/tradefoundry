# TradeFoundry architecture checkpoint

This is the short, persistent context that must be reviewed before starting every new board.
The authoritative detail remains in `../TradeFoundry-Architecture-v1.md` and
`../TradeFoundry-Nine-Boards-Detailed-v1.md`.

## Dependency chain

```text
SourceRecord
  -> RawArtifact -> EvidenceFragment -> Claim
  -> Entity / Product / Relation
  -> WorldEvent -> TradeHypothesis
  -> DealCell -> DealRoute -> Experiment -> Action -> Observation
  -> ScoreSnapshot / BudgetAllocation / PolicyDecision
  -> RFQ / Quote / Interaction / NegotiationTerm
  -> Order / Shipment / Invoice / Payment / Outcome
```

## Board status

| Board | Domain | Status | Reliable output boundary |
|---|---|---|---|
| 1 | Global sensors and source governance | completed | immutable source records, artifacts, changes and health |
| 2 | Evidence vault and document intelligence | completed | cited, reviewed and temporal Claims |
| 3 | Commercial world model | completed | reversible Entity/Product/Relation master data |
| 4 | Opportunity compiler | completed | audited TradeHypothesis and Deal Cell create command |
| 5 | Deal Cell and route experiments | completed | durable deal/route state, experiments, actions, observations and budget ledger |
| 6 | TradeAlpha and portfolio | completed | temporal scores, distributions, valuations and constrained allocations |
| 7 | Bilateral commercial execution | completed | governed RFQs, quotes, interactions, qualification and terms |
| 8 | Financial risk, compliance and approvals | next | costs, policy decisions and approvals |
| 9 | Orders, cash and learning | pending | execution ledger and Outcomes |

## Non-negotiable invariants

1. Modules exchange versioned contracts; they do not write another board's internal tables.
2. Claims report what evidence says. Inference remains separately labelled and never becomes a fact by wording.
3. Important conclusions trace to a Claim and original evidence; important numbers cite their source.
4. Business time and recorded time are separate; derived values carry model/rule/prompt versions.
5. Commands are idempotent. History, rejection, failure and stop outcomes are retained.
6. No external side effect exists without a later PolicyDecision, approval, idempotency key and audit.
7. Board 4 does not score or allocate money. Board 5 does not bypass policy to execute an action.
8. Codex proposes, explains and audits. Trade Core owns facts, state, amounts and authority.
9. The MVP remains a modular monolith with PostgreSQL-compatible models and adapters around open source.
10. A downstream board can trust an upstream output only after its board gate passes.
11. Route stage and route lifecycle are independent; observations propose impact but never rewrite
    probability, stage or history. Spend is append-only and every limit change names an approver.
12. TradeAlpha is advisory and append-only. Hard compliance/risk constraints remain independent of
    score, small data keeps wide intervals, and no Outcome means a rule baseline rather than learning.
13. Board-seven commercial records are facts or drafts, never policy authority. Live outbound is
    disabled until board eight supplies current policy, approval, freeze checks and production tokens.

## Board-seven handoff boundary

Board seven consumes canonical Entity/Product/Claim references, Deal Routes and approved advisory
inputs. It owns supplier/buyer commercial profiles, RFQ versions, supplier quote facts and comparison
snapshots, contact points and suppressions, grounded message drafts, send audit records, interactions,
qualifications, constraint assessments, buyer quote drafts, negotiation versions and meeting action
proposals. It never copies canonical company identity, changes a Route stage, calculates authoritative
landed cost, decides compliance or creates orders/accounting truth.

Board eight must implement deterministic Money/FX/cost scenarios and the current policy, approval,
execution-token and freeze authority behind the existing ports. Board seven's default ports deny
communication and reject buyer-quote construction; its default gateway cannot deliver live messages.
The local token and recording gateway are acceptance scaffolding, not production authorization.
Board nine remains the authority for orders, payments, P&L and learning Outcomes.

## Start-of-board review

Before implementation, read this checkpoint, the target board section in the nine-board document,
the responsibility matrix, the preceding board ADR/report and the current README. Then restate:

- target inputs and outputs;
- what the board is forbidden to decide or execute;
- independently testable submodules;
- reusable open-source components and rejected dependencies;
- migration, replay, safety and final acceptance gates.
