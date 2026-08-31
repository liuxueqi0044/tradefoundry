# Board 8 operations runbook

## Safe control flow

1. Ingest FX quotes with base/quote direction, exact Decimal rate, source, quote time and expiry.
   Never infer parity or reverse a pair without recording the resulting conversion direction.
2. Version cost definitions before use. Review allocation basis, required status and the Incoterms in
   which a component is already included.
3. Calculate a landed-cost scenario from pinned quote/route/destination inputs. Stop on `incomplete`;
   review assumptions, missing components, uncertainty range, line sources and input hash.
4. Build dated cashflow events in one reporting currency. Review peak working capital, capital days,
   financing rate and the financing line rather than treating contribution margin as cash need.
5. Re-run sensitivity from the same base inputs. Best/worst labels are deterministic scenarios, not
   probability claims or authorization to spend.
6. Treat no-history credit as `unknown`. A human override needs evidence, reason and expiry and does
   not rewrite the original assessment.
7. Synchronize each official/approved compliance source into a new immutable version. Validate
   publisher, publication/effective time, content hash, license and count before activation. Record a
   refresh failure and keep the previous active version.
8. Screen canonical subjects and relevant owners. Exact identifiers block. Fuzzy, incomplete or
   possible matches remain reviewable and frozen; never change a threshold to clear one case.
9. Evaluate product, destination, buyer and end use against active effective-dated export datasets.
   Missing end use is review-required and a candidate code is not a legal classification.
10. Preserve every tariff, certification and remedy candidate when product codes are ambiguous.
    Rates must come from the pinned dataset version.
11. Pass board-seven contact point, lawful basis, jurisdiction, retention and active suppression facts
    to the unified policy engine immediately before communication. Suppression takes precedence.
12. Activate only reviewed policy bundles. Missing configuration denies. In OPA deployments, retain
    bundle revision and decision ID and monitor bundle freshness and decision-log delivery.
13. Create an approval request for the exact action, subjects and parameter hash. Follow ordered
    steps; enforce amount tiers, expiry and separation of duties.
14. Issue a short-lived token only for an approved, unexpired and unfrozen request. Return the raw
    value once, protect it as a secret and never log it.
15. Reserve through the execution guard, perform the external effect with the same effect key, record
    its receipt and consume the token in the shared transaction. A changed parameter hash, expired
    token, current freeze or second consumption must fail.
16. Open cases and freezes idempotently from non-clear screening or operational incidents. Release
    only after independent, evidence-backed review; retain the original freeze and release record.
17. Export audit packages by resource and time window. Use operational redaction by default and grant
    full auditor output only under the deployment's access policy.

The HTTP boundary is `/v1/control`; interactive schemas are available at `/docs`. Policy bundles and
compliance datasets are deliberately not auto-seeded. A new environment therefore denies controlled
actions until an operator loads and activates reviewed versions. The OPA adapter and board-seven
execution guard are provider seams; the repository does not start an OPA service or a live messaging
gateway.

## Verification

```powershell
uv run ruff check .
uv run pytest -q
$tests = Get-ChildItem tests -Filter 'test_s8*.py' | ForEach-Object { $_.FullName }
uv run coverage run --source=tradefoundry.controltower --omit='*/controltower/api.py,*/controltower/adapters.py' -m pytest -q $tests
uv run coverage report --omit='*/controltower/api.py,*/controltower/adapters.py' --fail-under=90
uv run alembic check
```

The API and board-seven adapters are intentionally thin integration code and have dedicated HTTP and
end-to-end acceptance tests. Include them in an informational report when desired; the core service
gate remains 90%.

## Incident rules

- FX source, direction or quote time is missing: reject the scenario; do not repair it with an
  unrecorded rate.
- An Incoterm-included charge appears again as an added component: quarantine the cost definition and
  scenario; retain both versions for investigation.
- Compliance refresh fails: keep the prior active dataset, record the failure and assess its staleness
  against the deployment SLA. Do not activate a partial snapshot.
- Screening unexpectedly clears incomplete identity: freeze execution, retain the run and review the
  completeness and threshold configuration as a control defect.
- Possible or blocked match has no freeze: stop all related external effects and open a severity-one
  control incident.
- Policy bundle missing or OPA unavailable: remain denied. Do not replace the engine with a local
  allow flag.
- Approval parameters differ from execution parameters: reject and create a new policy/approval
  chain for the new hash.
- Raw token appears in a database, log or audit package: revoke/freeze affected actions, rotate
  relevant secrets and handle as a credential-exposure incident.
- Provider effect succeeds but local consumption fails: keep the token reserved, reconcile by effect
  key/provider receipt and never blindly retry the external call.
- Freeze released by the opener or without evidence: restore the freeze and investigate the bypass;
  do not edit the old release row.

## Rollback

Application rollback may continue reading board-eight decisions and scenarios. Database downgrade to
`88c2ba6654a7` removes the control-token reference from board-seven outbound records and drops all
twenty-eight financial, compliance, approval and audit tables. It is allowed only for disposable/local
databases or after an approved backup and complete regulator/auditor export. Production risk,
approval, execution and freeze history must be retained and rolled forward.
