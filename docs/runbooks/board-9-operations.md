# Board 9 operations runbook

## Safe execution and learning flow

1. Confirm the DealRoute is `committed` through Board 5 and retain the formal commitment Claim and
   fragments. Do not create an order from a quote draft or optimistic probability.
2. Synchronize Customer/Supplier and Item mappings through the trusted ERP integration operator.
   Review provider, resource type, internal ID, ERP external ID and outbox attempt history.
3. Obtain Board 8 policy decision, independent approval and short-lived token for the exact
   `create_order` action, order key and canonical parameter set. Never log the raw token.
4. Queue the ERP-native minimal Sales/Purchase Order payload. Reserve the token, perform one effect
   and consume it only after an external identifier is returned.
5. Retry only refused connections. Treat timeout, 5xx or missing external ID as ambiguous; query ERP
   by the deterministic reference before deciding whether another write is safe.
6. Ingest ERP events into immutable snapshots. Route commercial differences and unknown external
   orders to review; do not overwrite the accepted command.
7. Record fulfillment milestones with verified Claim fragments and new versions. Validate the latest
   invoice, packing list, bill of lading, customs document and certificate as one consistent set.
8. Ingest sales/purchase invoice references from ERP. For cross-currency facts, cite the exact Board
   8 MoneyConversion; never accept an operator-entered exchange rate.
9. Record payments, allocation evidence and the originating bank statement reference. Bank
   reconciliation requires a separate ERP reconciliation reference and evidence and is immutable.
10. Publish collection only after every non-void sales invoice is fully allocated and every
    contributing payment is bank-reconciled. The adapter must let Board 5 evaluate the committed to
    collected transition; never edit the route table.
11. Open quality/claim cases against order, batch, supplier and buyer. Append reserves/events; a
    reviewer different from the reporter closes with conclusion, evidence and final loss.
12. Build realized contribution P&L from invoice, actual-cost, payment-fee/FX and closed-quality
    facts. Compare to a cited ERP ledger close and resolve any `review` difference before success.
13. Build a successful Outcome only from published collection and reconciled P&L. Retain stopped,
    failure and no-reply Outcomes with their failed stage or reason.
14. Compare the Outcome only to score, probability and Board 8 cost snapshots that existed before the
    prediction cutoff and to the exact P&L snapshot pinned by the Outcome.
15. Materialize learning examples from real FeatureSnapshots whose `as_of`, source availability and
    creation time precede the observation cutoff, which must precede the Outcome. Keep failures,
    human interventions and exploration markers.
16. Evaluate challengers on the immutable dataset and a strict out-of-time window. Require
    calibration, critical slices, economic comparison and safety checks. Eligibility creates a
    review proposal only.
17. Publish dashboard snapshots from cited invoice, P&L, cashflow and Outcome facts at/before `as_of`
    in one reporting currency. Keep sales and contribution profit separate.

The HTTP boundary is `/v1/execution`; interactive contracts are at `/docs`. The public shipment-
document read is always redacted. The default ERP endpoint queues only and the HTTP gateway starts
disabled. Production webhook/API authentication belongs to the trusted reverse-proxy/integration
runtime and must not be replaced with a query flag or committed credential.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
$tests = Get-ChildItem tests -Filter 'test_s9*.py' | ForEach-Object { $_.FullName }
uv run coverage run --source=tradefoundry.execution --omit='*/execution/api.py,*/execution/adapters.py' -m pytest -q $tests
uv run coverage report --omit='*/execution/api.py,*/execution/adapters.py' --fail-under=90
uv run alembic check
```

Thin FastAPI/provider wiring has dedicated OpenAPI, HTTP transport and end-to-end tests. The core
domain coverage gate remains 90%.

## Incident rules

- Raw Board 8 token or ERP credential appears in SQL/log/export: freeze the affected action, rotate
  the secret, preserve the exposure evidence and investigate every attempted effect.
- ERP timeout, 5xx or success response without ID: mark ambiguous, stop automatic retry and reconcile
  by provider reference/outbox fingerprint.
- ERP event has no local mapping: keep `unmapped`, open review and do not attach it by fuzzy guess.
- Order was created for a non-committed route or without exact token binding: freeze further effects,
  reconcile the ERP order and open a control incident; do not delete the command.
- Shipment-document set is missing, expired or version-inconsistent: block downstream document use,
  append corrected versions and retain the issue.
- Caller-provided normalized money differs from Board 8: reject the write and review the cited
  conversion; never adjust the frozen conversion in place.
- Collection signal appears before full allocation/bank reconciliation: freeze stage advancement,
  retain invoices/payments/allocations and investigate the publisher boundary.
- Bank reconciliation changes after recording: reject it; append an operational correction workflow
  outside the immutable fact instead of editing history.
- P&L differs from ERP close: keep `review`, identify invoice/cost/fee/FX/claim sources and do not
  label the transaction successful.
- Reporter closes their own quality case: reject and assign an independent reviewer.
- Feature or upstream snapshot is later than its cutoff: quarantine the dataset version and every
  dependent evaluation; rebuild from an earlier immutable snapshot.
- Challenger has missing safety/economic/slice evidence or tries to auto-promote: mark ineligible,
  retain the report and open a governance incident if an effect was attempted.

## Rollback

Application rollback may continue reading Board 9 facts. Database downgrade to `e3027c909abe`
drops all twenty-six execution, settlement and learning tables. It is allowed only for disposable
local databases or after an approved backup plus complete ERP/accounting/learning audit export.
Production order, payment, reconciliation, quality, P&L and Outcome history must be retained and
rolled forward. Downgrading TradeFoundry does not reverse an ERPNext order or bank transaction.
