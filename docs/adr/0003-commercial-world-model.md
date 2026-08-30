# ADR-0003: Commercial world model and reversible identity resolution

- Status: accepted
- Date: 2026-08-30
- Decision owner: Sol
- Scope: S3.1–S3.9

## Context

TradeFoundry receives multiple claims about the same companies, people, projects, procurements, awards, products and locations. Names vary by language, legal suffix and address history. False merges are more damaging than temporary duplicates because they can combine sanctions risk, relationships, product capability and commercial decisions across different legal persons.

## Decision

Board three remains a `master` package in the modular monolith and consumes validated or verified Claims. It never rewrites Claim ownership or Relation endpoints during entity resolution.

```text
validated Claim
  -> source Entity + raw Alias/Attribute/Identifier
  -> deterministic strong-identifier check
  -> explainable probabilistic candidates
  -> human/automatic merge command or distinct constraint
  -> dynamic canonical profile + provenance-selected golden fields
  -> ProductConcept / Specification / temporal Relation
  -> name, identifier, product and 1–3 hop graph query API
```

Each source entity remains a permanent record. A merge changes only the losing root's `canonical_entity_id` and appends a `MergeCommand`. A split or undo removes that pointer through an audited command. Claims, aliases, identifiers and relations continue pointing to their original source entities, so a later split does not require reconstructing lost evidence.

## Identity rules

1. Entity types are stored as extensible strings but validated against the initial domain contract at the API boundary.
2. Unicode, casing, legal suffixes and common address tokens are normalized while the original value and Claim remain intact.
3. LEI checksums, EU VAT identifiers, domains, emails and international telephone numbers use specialized open-source validators/normalizers.
4. Exact strong identifiers auto-merge compatible, unfrozen entities unless an active human distinct constraint exists.
5. A strong identifier that contradicts entity type, a freeze or a distinct constraint creates an `IdentityConflict`; both roots freeze until explicit review.
6. Probabilistic results persist model version, snapshot hash, probability, every feature and threshold. Low-confidence results enter a review queue.
7. Probabilistic auto-merge is off by default. Entity type and risk tier raise the threshold when it is explicitly enabled.
8. Human rejection creates a durable distinct constraint, preventing a future matching run from silently re-merging the pair.

The online baseline is a versioned logistic scorer over RapidFuzz name/address similarity and exact domain, telephone and country features. It is deliberately small and explainable. Splink is pinned as an optional batch/challenger dependency for trained probabilistic linkage once a representative labelled corpus exists; the domain tables do not depend on Splink's internal schema.

## Golden records

Canonical profiles are projections, not copied mutable master rows. Every golden field returns its normalized and raw values, source entity, source Claim, confidence, source priority and selection reason. Verified Claims outrank merely validated Claims; source priority and confidence break ties. The golden name is selected by the same provenance principle.

## Products and specifications

`ProductConcept` is linked to a product Entity and can have a parent and multilingual synonyms. HS, CPV, PSC and other mappings start as candidates with method and confidence. They become verified only through an explicit review.

Specifications preserve source text and normalize quantities through the board-two Pint unit system. Required, optional, range and tolerance requirements have stable keys, so two specification versions can produce added, removed, changed and unchanged differences without discarding original wording.

## Relations

The initial graph is a PostgreSQL-compatible adjacency table. Every edge has an evidence Claim, confidence, review state and validity interval. Relation endpoints retain source entity IDs; queries resolve them to current canonical roots dynamically. Breadth-first one-to-three-hop traversal is sufficient for the current scale and keeps SQLite acceptance portable. A graph database is deferred until measured query load justifies dual-write and synchronization cost.

## Open-source reuse

- **RapidFuzz** supplies optimized string similarity.
- **phonenumbers** implements international telephone parsing and E.164 formatting.
- **python-stdnum** validates LEI and EU VAT formats/checksums.
- **Pint** is reused from board two for dimensional specification normalization.
- **Splink** is an optional batch/challenger environment, not a domain dependency.
- Existing SQLAlchemy, Alembic, Pydantic and FastAPI infrastructure is reused.

## Consequences and deferred gates

Canonical lookup costs more than destructive foreign-key rewrites, but merge reversal and evidence preservation become reliable. The local implementation scans small candidate sets and adjacency rows in Python; PostgreSQL blocking/index tuning, pg_trgm, trained Splink calibration and performance testing are production-scale gates. Entity/contact APIs contain potential PII and must be protected by platform IAM and retention policy before external exposure.
