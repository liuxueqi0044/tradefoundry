# Board 7 operations runbook

## Safe bilateral flow

1. Create supplier and buyer profiles only from active canonical Entities and cited Claims. Review
   factory/trader/agent classification, capabilities, certifications and contact lawful basis.
2. Add supplier candidates with discovery source and explicit gaps. Platform display prices remain
   discovery metadata and must never be copied into a SupplierQuote.
3. Obtain Board-8 policy approval before changing a route candidate to `whitelisted`.
4. Generate a versioned Chinese RFQ. Resolve every listed missing specification, quantity, package,
   certification, delivery, payment and Incoterm field before finalization.
5. Authorize only the final content hash for one route-specific whitelisted supplier. Never copy a
   token to another supplier or edit the RFQ after review.
6. Preserve the raw email/file/manual record and hash before structured quote intake. Review every
   `uncertain_fields` entry and quotation expiry.
7. Compare quotes only with an explicit target unit, currency and Incoterm. Every FX rate names a
   source and time; every Incoterm delta is an explicit per-quote adjustment. Keep incomparable rows.
8. Record supplier prediction and actual performance separately by product. Do not rank a supplier
   whose snapshot is `insufficient_history` as if it had a perfect score.
9. Evaluate communication eligibility immediately before drafting. Active unsubscribe, complaint,
   do-not-contact or jurisdiction suppression takes precedence over policy allow.
10. Generate a Claim-grounded draft. Resolve prohibited findings and review the listed human
    confirmations. First contact needs a separate human-approved, short-lived token.
11. Send only through the outbound gateway. It rechecks current whitelist or suppression and pins the
    resource version, recipient, payload hash, approver, provider receipt and operator.
12. Preserve inbound raw artifacts. Use explicit or exact-thread Route linking; resolve the human
    queue rather than accepting a fuzzy suggestion automatically.
13. Treat intent as a reviewable classification. A low-confidence row never changes Route stage;
    absence of a reply is not an Interaction and is not rejection.
14. Record quantity, specification, budget, timing, authority and procurement process separately.
15. Re-run the constraint coordinator whenever either side changes MOQ, delivery, certification,
    payment or specification. Candidate solutions are proposals, not commitments.
16. Build buyer quotes only from the Board-8 immutable cost-scenario port. Estimated cost remains
    labelled and every quote stays `pending` approval; there is no board-seven buyer-quote send path.
17. Append negotiation versions. Review every diff and route floor breach to Board-8 approval.
18. Import meeting action items idempotently. They remain board-seven proposals until board five
    accepts them through its public Action boundary.

The HTTP boundary is `/v1/bilateral`; interactive schemas are available at `/docs`. In the current
MVP, `DenyAllPolicyPort`, `UnavailableCostScenarioPort` and `DisabledOutboundGateway` are deliberate
safe defaults. Replacing only the gateway is forbidden: policy, approval, freeze and production token
validation must be integrated together.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
$tests = Get-ChildItem tests -Filter 'test_s7*.py' | ForEach-Object { $_.FullName }
uv run coverage run --source=tradefoundry.bilateral --omit='*/bilateral/api.py' -m pytest -q $tests
uv run coverage report --omit='*/bilateral/api.py' --fail-under=90
uv run alembic check
```

For service-domain coverage, omit the thin `bilateral/api.py` router; its safe defaults, HTTP error
mapping and OpenAPI resource families have dedicated API tests.

## Incident rules

- Display price appears as a quote: quarantine the record and inspect the adapter; do not correct it
  by editing history.
- RFQ changed after approval: invalidate the token and generate/finalize a new RFQ version.
- Duplicate provider send: stop the gateway, retain both receipts and audit provider idempotency use.
- Unsubscribe or complaint after token issuance: keep the suppression active; send must fail. Treat a
  delivered message after that check as a severity-one communication-control defect.
- Quote comparison looks unexpectedly cheap: inspect unit factor, FX source/time, tax and Incoterm
  adjustment before making any supplier decision.
- Ambiguous reply linked to a Route: move it to review; never use fuzzy score alone as identity.
- Intent low confidence or contradictory: leave stage unchanged and assign human review.
- Buyer quote does not name a cost hash/calculator version: reject it and reconnect Board-8 costs.
- Negotiation floor breached: retain the version and request approval; do not overwrite the term.
- Constraint conflict disappears without a new input snapshot: stop use and compare pinned IDs.

## Rollback

Application rollback may continue reading board-seven tables. Database downgrade to `b12859bb770b`
drops supplier/buyer commercial profiles, RFQs, quotes, comparison snapshots, contact suppressions,
message drafts, send tokens/audit, interactions, qualification, constraints, buyer quote drafts,
negotiation versions and meeting tasks. It is allowed only for disposable/local databases or after an
approved backup/export. Production communication and negotiation history must be retained and rolled
forward.
