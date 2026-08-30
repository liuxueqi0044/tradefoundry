# ADR-0002: Evidence vault and Claim architecture

- Status: accepted
- Date: 2026-08-30
- Decision owner: Sol
- Scope: S2.1–S2.10

## Context

TradeFoundry must turn heterogeneous source documents into conclusions that can survive commercial, financial and compliance review. Extracted text by itself is insufficient: every field must remain tied to the exact immutable bytes, document version and original location that support it. Model output must also be treated as an untrusted proposal, not as a fact.

## Decision

Board two remains a bounded package inside the modular monolith. It reuses board one's content-addressed artifact store and adds append-oriented `evidence_*` tables. The processing chain is:

```text
immutable artifact
  -> logical document version + security verdict
  -> versioned conversion run
  -> page/bbox/section/table-cell fragments
  -> versioned JSON Schema + extraction run
  -> cited Claim candidates
  -> deterministic normalization + temporal conflict detection
  -> append-only human decision
  -> evidence package API
```

The following invariants are mandatory:

1. Identical bytes have one physical object but may appear in multiple immutable logical document versions.
2. Quarantined content cannot be converted or produce Claims.
3. Conversion output is persisted with converter and schema versions. A failed conversion is also audited.
4. Every machine-extracted Claim cites one or more fragments belonging to the same document.
5. JSON Schema and the internal Claim envelope both validate before any Claim is persisted.
6. Missing units and ambiguous dates are marked for review; the system does not infer them.
7. Different values for the same subject and field with overlapping validity form a conflict group; neither value overwrites the other.
8. Human correction creates a new Claim linked by `supersedes_claim_id`; the original model Claim and raw extraction output remain intact.
9. Retrieval returns the conclusion, support status, artifact hash/URI, document version and every original location in one package.

## Open-source reuse

- **Docling v2** is the optional PDF/Office/OCR adapter. Its output is translated into the internal `NormalizedDocument` port so it can be upgraded or replaced without changing Claim semantics.
- **Beautiful Soup** performs non-executing HTML structure extraction.
- **JSON Schema Draft 2020-12** validates extraction contracts.
- **Pint** handles dimensional quantities and explicit unit conversion.
- **python-dateutil** parses non-ambiguous dates; **py-moneyed** validates ISO 4217 codes.
- Existing **FastAPI**, **Pydantic**, **SQLAlchemy** and **Alembic** infrastructure is reused.

Docling is an adapter, not a domain dependency. Tests exercise the v2 `DocumentConverter`, `iterate_items`, provenance, error and table-cell contract without downloading model weights. A deployment that processes real PDF/OCR files installs the `documents` extra and runs a version-pinned golden corpus before promotion.

## Security decisions

- File type is detected from signatures/container structure rather than trusted extension alone.
- Size, MIME spoofing, damaged/encrypted archives, path traversal, member count, expanded size, compression ratio, macro-enabled Office extensions and the EICAR test marker have explicit quarantine paths.
- Active HTML content is removed before fragment creation.
- The bundled scanner is an explicitly named development tripwire. Production mode fails closed until a real malware-scanner adapter is injected.
- Original artifact bytes are never executed or mutated.

## Alternatives rejected

- Building an OCR/layout engine from scratch: high cost, worse maintenance and no domain advantage.
- Storing only Markdown or whole-document citations: cannot prove a field at page/region/table-cell granularity.
- Letting LLM output write business facts directly: breaks validation, provenance and auditability.
- Updating a single “current fact” row: destroys temporal truth and hides conflicts.
- Splitting every S2 capability into a service: adds distributed transactions and operational burden before scale requires it.

## Consequences

The database stores more historical rows and normalized conversion JSON, but replay, audit, correction and time-travel queries remain possible. Heavy document conversion can later move to an isolated worker without changing the database or service contracts. Authentication, reviewer identity federation, retention policy and entity resolution remain later-board/infrastructure concerns.
