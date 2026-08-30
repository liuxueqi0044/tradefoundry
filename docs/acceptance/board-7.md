# Board 7 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S7.1 | A SupplierProfile references one canonical Entity, distinguishes factory/trader/agent and retains multiple field Claims plus reviewed product capabilities | `test_s7_1_2_suppliers.py` |
| S7.2 | A route candidate retains discovery basis, source Claims and missing fields; a platform display price is permanently marked non-quote and whitelisting needs policy allow | `test_s7_1_2_suppliers.py` |
| S7.3 | Versioned Chinese RFQs map specification, quantity, packaging, certification, delivery, payment and Incoterm; every missing item becomes an explicit question and blocks finalization | `test_s7_3_4_rfq.py` |
| S7.4 | Only a final RFQ for a currently whitelisted route supplier can receive an approved, expiring, payload-bound, single-use token; retry is idempotent and the exact sent version is retained | `test_s7_3_4_rfq.py` |
| S7.5 | Standard email, CSV spreadsheet and manual adapters extract common quote fields; the persisted quote retains raw artifact/hash, format, expiry and uncertain fields for review | `test_s7_5_7_quotes_performance.py` |
| S7.6 | Pint units, versioned FX inputs and explicit per-quote Incoterm adjustments create a reproducible comparison; missing conversions make a quote incomparable instead of guessed | `test_s7_5_7_quotes_performance.py` |
| S7.7 | Product-level supplier snapshots separate predicted from actual events and return no score below minimum actual history | `test_s7_5_7_quotes_performance.py` |
| S7.8 | Buyer profiles reference canonical Entities; contacts retain normalized sourced points, lawful basis and multiple time-bounded roles | `test_s7_8_11_crm_outreach.py` |
| S7.9 | Active unsubscribe/complaint/do-not-contact/jurisdiction suppression is evaluated before policy and prevents sendable eligibility | `test_s7_8_11_crm_outreach.py` |
| S7.10 | Deterministic drafts use text that is checked against recorded Claims, list human confirmations and block unsupported customer/certification/price/delivery assertions | `test_s7_8_11_crm_outreach.py` |
| S7.11 | Every first contact requires a separate human-approved token; late suppression still blocks the only send gateway | `test_s7_8_11_crm_outreach.py` |
| S7.12 | Raw interaction artifacts, hashes and attachments are retained; explicit/exact-thread links are accepted and ambiguous matches enter a human queue | `test_s7_12_14_interactions.py` |
| S7.13 | A versioned golden-rule classifier identifies interest, rejection, clarification and objections; low confidence does not mutate Route stage and silence is not rejection | `test_s7_12_14_interactions.py` |
| S7.14 | Quantity, specification, budget, timing, authority and procurement process remain separate, cited fields; missing values remain null and explicit | `test_s7_12_14_interactions.py` |
| S7.15 | The coordinator detects MOQ, delivery, certification, payment and specification conflicts and emits only human-review candidate adjustments plus a reassessment signal | `test_s7_15_18_coordination.py` |
| S7.16 | A buyer quote reads a hash/versioned cost scenario from the Board-8 seam, distinguishes estimated/confirmed cost and remains an unapproved draft | `test_s7_15_18_coordination.py` |
| S7.17 | Negotiation terms append immutable versions and diffs; floor breaches are retained without exposing the full floor snapshot and require approval | `test_s7_15_18_coordination.py` |
| S7.18 | A meeting creates a linked Interaction and route/owner/deadline task proposals exactly once under repeated import | `test_s7_15_18_coordination.py` |

## Board-level scenario

`test_s7_board_acceptance.py` creates a complete technical RFQ, sends its pinned version to three
separately whitelisted and approved sandbox suppliers, imports email/CSV/manual quotes, explicitly
normalizes unit/currency/Incoterm, records a buyer's shorter delivery and Net-60 request, then returns
comparable differences, five conflict families and human-only candidate adjustments.

## Production gates not claimed by this acceptance

1. The recording gateway proves idempotency and audit behavior but never contacts a live provider.
2. Board eight must supply the current OPA/policy evaluation, approval chain, compliance freeze and
   production action token; Board seven's default ports deny.
3. The accepted spreadsheet adapter is CSV. XLSX/vendor templates require a versioned adapter and
   golden fixtures before activation.
4. Quote extraction is deterministic key/value parsing. OCR, free-form attachments and LLM-assisted
   extraction must preserve raw evidence, confidence and human review and are not production claims.
5. Buyer quote drafts use a mocked Board-8 cost port in acceptance. No arbitrary request amount is
   accepted and no buyer quote can be sent from this board.
6. Production email reputation, bounce processing, domain authentication, privacy retention,
   provider webhooks, rate limits and jurisdiction-specific legal review remain deployment gates.
