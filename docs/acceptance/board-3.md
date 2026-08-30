# Board 3 acceptance contract

| ID | Independently accepted outcome | Evidence |
|---|---|---|
| S3.1 | One extensible model supports organization, person, project, procurement, award, product and location while preserving source Claim and alias | `test_s3_1_entity_model.py` |
| S3.2 | Multilingual names, legal suffixes, addresses, domains, emails and telephones normalize deterministically while raw values remain | `test_s3_2_normalization.py` |
| S3.3 | Exact strong identifiers merge compatible roots; contradictions freeze rather than merge; human conflict review is reversible and audited | `test_s3_3_strong_identifiers.py` |
| S3.4 | Probability candidates persist calibrated inputs, model version, probability and explanations; golden pairs meet precision/recall thresholds; review can accept/reject | `test_s3_4_probabilistic_resolution.py` |
| S3.5 | Merge, undo and split preserve source aliases, Claims and Relations; golden fields explain provenance priority | `test_s3_5_merge_split_golden.py` |
| S3.6 | Product concepts support hierarchy and multilingual synonyms; classification codes remain candidates until explicit verification | `test_s3_6_product_ontology.py` |
| S3.7 | Specifications support required/optional/range/tolerance/unit semantics; diffs retain original text | `test_s3_7_specifications.py` |
| S3.8 | Parent, buyer, EPC, award and other relationships carry Claim, confidence, review state and effective time; expired edges disappear from traversal | `test_s3_8_relationship_graph.py` |
| S3.9 | API searches multilingual names/identifiers/products, returns canonical profile evidence, and traverses one to three hops | `test_s3_9_master_api.py` |

## Board gate

Sol rejects the board if any merge is irreversible, any verified product code silently originates from a candidate, any graph edge lacks a reliable Claim, or a matching probability lacks feature/model explanation.

## Production promotion gates

1. Calibrate and evaluate match probabilities on a representative, time-separated labelled corpus. Enable probabilistic auto-merge only after entity-type-specific precision requirements pass.
2. Configure PostgreSQL blocking/index strategy and load-test name, identifier and three-hop queries at target volume.
3. Protect person, email and phone fields with platform IAM, field-level logging rules, retention and deletion procedures.
4. Review registration/VAT schemes jurisdiction by jurisdiction; generic normalization is not legal validation.
5. Benchmark the optional Splink challenger against the explainable baseline and preserve evaluation artifacts before promotion.
