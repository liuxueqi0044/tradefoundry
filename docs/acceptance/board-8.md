# Board 8 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S8.1 | Same-currency Decimal arithmetic is exact, mixed-currency addition fails and every FX conversion retains quote direction, rate, source, time and idempotency | `test_s8_1_6_finance.py` |
| S8.2 | Versioned cost definitions distinguish fixed, per-unit, per-weight and ad-valorem allocation and declare required and Incoterm-included behavior | `test_s8_1_6_finance.py` |
| S8.3 | A hand-calculated landed-cost golden case matches exactly, replays by input hash, exposes assumptions/missing costs and rejects double counting | `test_s8_1_6_finance.py` |
| S8.4 | Dated inflows/outflows, financing cost, peak working capital and capital days are deterministic across payment and date boundaries | `test_s8_1_6_finance.py` |
| S8.5 | Replayable base/best/worst cases report each variable's effect on profit and peak working capital | `test_s8_1_6_finance.py` |
| S8.6 | No-history credit is unknown with a conservative limit; a time-bounded human override requires a reason and evidence | `test_s8_1_6_finance.py` |
| S8.7 | Compliance datasets retain publisher, source, publication/effective time, license and content hash; a failed sync keeps the previous active version | `test_s8_7_10_compliance.py` |
| S8.8 | Exact identifiers block, fuzzy/incomplete identity never auto-clears, match fields and scores are explained, ownership risk propagates and non-clear outcomes freeze | `test_s8_7_10_compliance.py` |
| S8.9 | Export-control candidates come from an effective-dated dataset; absent end use requires review and no model output becomes a final classification | `test_s8_7_10_compliance.py` |
| S8.10 | Ambiguous product codes preserve multiple tariff/certification/remedy candidates and their effects; rates and dates are data, not code or prompt constants | `test_s8_7_10_compliance.py` |
| S8.11 | First contact, follow-up, lawful basis, retention, jurisdiction and board-seven suppressions are evaluated by the unified versioned policy engine | `test_s8_11_16_privacy_audit.py` |
| S8.12 | Identical policy inputs return a deterministic versioned decision, restrictive same-priority rules win, execution defaults deny without active policy and the OPA seam preserves decision/revision IDs | `test_s8_11_15_governance.py` |
| S8.13 | Single, dual and tiered approval chains advance in order, expire, bind parameter hashes and reject self-approval or parameter tampering | `test_s8_11_15_governance.py` |
| S8.14 | One approved request issues one short-lived opaque token bound to action, resource and parameters; reservation is idempotent and consumption is single-use | `test_s8_11_15_governance.py` |
| S8.15 | A possible match or later risk event immediately freezes affected actions; release needs an independent reviewer and evidence and never erases history | `test_s8_7_10_compliance.py`, `test_s8_11_15_governance.py` |
| S8.16 | A role-aware export links financial, evidence, screening, policy, approval, token and freeze records, is hashable/replayable and redacts operational output | `test_s8_11_16_privacy_audit.py` |

## Board-level scenario

`test_s8_board_acceptance.py` starts from board-seven buyer, contact, draft and message records. It
calculates a multi-currency CIF scenario and cash peak, detects a possible sanctions-name match,
opens a case and freeze, and proves that the frozen subject cannot use an already approved action.
An independent evidence-backed release permits one newly bound control token, after which the real
board-seven outbound path records the effect once and rejects reuse.

## Production gates not claimed by this acceptance

1. Test compliance datasets are deterministic fixtures, not live or licensed official lists.
2. RapidFuzz is an explainable candidate matcher. Production screening still needs approved data,
   transliteration/alias policy, ownership coverage, tuned thresholds and trained reviewers.
3. The local policy backend proves deterministic semantics and default deny. Production OPA bundle
   signing, distribution, availability, decision-log retention and break-glass governance remain
   deployment work.
4. Candidate export, tariff, certification and trade-remedy results are not legal advice. Qualified
   reviewers must own final classification and jurisdiction-specific policy.
5. Financial scenarios are decision inputs, not ledger facts. Board nine must reconcile estimates to
   orders, invoices, payments, claims and actual FX.
6. The live communication gateway remains disabled. Provider credentials, domain reputation,
   provider idempotency, webhooks, rate limits and incident controls require a deployment review.
7. SQLite proves the portable contract and migration path; production PostgreSQL backup, restore,
   concurrency and failover exercises remain operational gates.
