# Board one acceptance map

Status is updated only from reproducible verification evidence.

| ID | Independent acceptance | Automated evidence |
|---|---|---|
| S1.1 | Missing license/schedule/access requirements block activation; every change creates a historical version | `test_s1_1_registry.py` |
| S1.2 | Reference connector resumes from cursor and emits bounded batches with raw artifacts | `test_s1_2_connector_contract.py` |
| S1.3 | Mock official API increments pages; rerun is idempotent; CSV bulk parses; invalid records quarantine | `test_s1_3_official.py`, `test_s1_6_runs_scheduler.py` |
| S1.4 | OCDS record, release and compiled-release relationships survive; invalid shapes quarantine | `test_s1_4_ocds.py` |
| S1.5 | Missing permission blocks execution; DOM change quarantines rather than fabricating data | `test_s1_5_web.py` |
| S1.6 | Create, pause, resume, cancel, checkpoint retry and full rerun obey state rules; due scheduling and worker deduplicate | `test_s1_6_runs_scheduler.py` |
| S1.7 | Added, generic update, revocation, deadline and attachment changes are independently emitted | `test_s1_7_changes.py` |
| S1.8 | Empty source, field drop, duplicate surge and repeated failure produce persistent alerts without stopping another source | `test_s1_8_quality.py`, `test_s1_6_runs_scheduler.py` |
| S1.9 | Fixed-window replay returns no diff for identical code/input and does not overwrite artifacts or records | `test_s1_9_replay.py` |

## Board-level manual scenario

1. Start with an empty database and artifact directory.
2. Create a disabled memory source with two pages and complete licensing metadata.
3. Activate it, create a fixed-window run and execute it.
4. Confirm two record observations, two current records, two change events and content-addressed artifacts.
5. Explicitly replay the same window.
6. Confirm `added_hashes=[]`, `missing_hashes=[]`, unchanged hashes are present, and artifact/record version counts do not grow.
7. Add a source version with changed content, reactivate and run a new window.
8. Confirm current projection changes while the previous version remains queryable.
