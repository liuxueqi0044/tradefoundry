# Board 4 acceptance specification

| ID | Independent acceptance result | Automated evidence |
|---|---|---|
| S4.1 | A set of verified facts creates one idempotent WorldEvent carrying time, country, subjects, products, reliability and original Claim links; unverified Claims are rejected | `test_s4_1_world_events.py` |
| S4.2 | Deterministic classification distinguishes RFQ, project approval, award, expansion, regulatory and disruption signals, preserving multiple labels and explanations | `test_s4_2_signal_classifier.py` |
| S4.3 | Opportunity templates are immutable versions with active/deprecated history, applicability gates, required evidence and forbidden conditions | `test_s4_3_templates.py` |
| S4.4 | Explicit, template-derived and provider-neutral LLM ProductNeed candidates retain evidence, derivation version and uncertainty; inference is never labelled fact | `test_s4_4_product_needs.py` |
| S4.5 | Buyer/EPC/distributor/supplier/awardee candidates require a direct event role or typed evidence relation path; generic affiliates are not promoted | `test_s4_5_participants.py` |
| S4.6 | Direct, pre-award, post-award and channel routes are emitted together; missing evidence produces a preserved excluded route with reasons | `test_s4_6_routes.py` |
| S4.7 | Every hypothesis is falsifiable and contains facts, inference, evidence, counter-evidence, unknowns, risks, probability range, no-side-effect probes, stop conditions and pinned compiler version | `test_s4_7_hypothesis_compiler.py` |
| S4.8 | Auditor returns PASS/NEEDS_DATA/REJECT and blocks unsupported numbers, missing evidence, expiry, hard prohibitions and template prohibitions | `test_s4_8_auditor.py` |
| S4.9 | Only a latest passing audit produces one idempotent versioned Deal Cell command; denied attempts retain reasons; HTTP flow is contract-tested | `test_s4_9_issuance_api.py` |

## Production gates not claimed by this acceptance

1. Precision/recall and economic value on a representative labelled opportunity corpus.
2. Production LLM/retrieval provider integration and prompt evaluation.
3. Board-eight policy service, sanctions/export-control integration and production authorization.
4. Board-five consumption, durable Deal Cell state and transactional outbox delivery.
5. Live PostgreSQL load, index and concurrency tests at target event volume.
