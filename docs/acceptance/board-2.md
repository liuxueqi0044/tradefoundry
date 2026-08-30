# Board 2 acceptance contract

This contract decomposes the evidence vault and document-intelligence board into independently testable work packages. A package is accepted only when its own tests pass and the prior board remains green.

| ID | Independently accepted outcome | Evidence |
|---|---|---|
| S2.1 | Same bytes occupy one physical object; logical versions remain distinct; reads rehash content | `test_s2_1_evidence_vault.py` |
| S2.2 | Over-limit, MIME-spoofed, malicious, unsafe-name, macro and unsafe/damaged archive inputs are quarantined | `test_s2_2_file_intake.py` |
| S2.3 | Conversion reconstructs pages/headings/tables, reports page errors, is idempotent and audits total failure | `test_s2_3_conversion.py` |
| S2.4 | A fragment preserves document version, page, bbox, section path and table-cell position | `test_s2_4_fragments.py` |
| S2.5 | JSON Schemas version, activate, deprecate and roll back; malformed schemas never enter the registry | `test_s2_5_schema_registry.py` |
| S2.6 | Structured output is schema-valid and every Claim cites an existing same-document fragment | `test_s2_6_claim_extraction.py` |
| S2.7 | Date, Decimal, currency and quantity normalize deterministically; missing units/ambiguous dates are not guessed | `test_s2_7_normalization.py` |
| S2.8 | Overlapping different values create a conflict; as-of queries distinguish then-current from current | `test_s2_8_conflicts_temporality.py` |
| S2.9 | Reviewer verifies/rejects/corrects with identity and reason; correction preserves original output and evidence trail | `test_s2_9_review.py` |
| S2.10 | One API package returns support state, conclusion, exact location, artifact hash/URI and document version | `test_s2_10_retrieval_api.py` |

## Promotion gates

Local/MVP acceptance uses deterministic fixtures. Before production promotion, operations must also provide:

1. A real malware-scanner adapter and fail-closed health check.
2. A jurisdiction/language representative PDF, scanned-image and Office golden corpus run with the pinned Docling build.
3. Authenticated reviewer identity rather than accepting reviewer text from an unauthenticated caller.
4. Object-store immutability/retention policy and backup restore evidence.
5. PostgreSQL migration verification against the actual deployment version.

These gates do not change S2 domain contracts; they validate deployment integrations and real data.
