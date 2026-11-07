# Item 2 only — independent notification obligations (0.5.1)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Scope and chronology

Repository: https://github.com/Zulfiqar7862/kestrel-adjudication-case-study ; branch `fix/correctness-review`.
The original item-2 commit is `2c7511580091de3231596c742c2bd3ff2a5b4c87`.
The user then narrowed scope to notification obligations only. Uncommitted item-3
work was restored to that commit and its new test file removed. No item-3–8 code
was committed. This follow-up is notification-only; production/main are untouched,
with no merge or PR. CI is watched after pushing; its URL/result is reported separately.

The six user acceptance criteria, not Claude's findings, define this change.
The earlier review/Claude sources were inspected as leads; no module was imported
wholesale and neither their conclusions nor green tests were treated as authority.

### Test-first evidence, including what was already implemented

Original item-2 development recorded **8 failing tests before implementation**, then
8 passing ([original red/green](../evidence-workflows/02-notifications.md)). The
six newly requested acceptance tests were written before this follow-up. Their
execution against an untouched exported `cd1bd24` baseline gives **6 failed**
([full output](acceptance-baseline-red.txt)). Several failures are explicitly
missing-feature errors, not claims that a live filing vanished.

Against the already-existing `2c75115` implementation, **4 failed, 2 passed**
([output](acceptance-followup-red.txt)): criteria 1 and 3 already worked; do not
misrepresent them as newly broken or as newly test-first implemented. The new
criterion-3 test also runs a fresh CLI process with the workbook unavailable.

| Criterion / test suffix in `TestNotificationAcceptance` | Observed pre-change failure on cd1bd24 | Observed final result |
|---|---|---|
| `test_criterion_1_signing_does_not_remove_outstanding_obligation` | `AttributeError: 'AdjudicationService' object has no attribute 'notifications'` | PASSED: signed disposition leaves the pending record unchanged, before any reopen |
| `test_criterion_2_assembly_failure_does_not_stop_deadline_tracking` | Same missing independent-lane AttributeError | PASSED: real adjudication raises the injected assembly error; SQLite lane/original alert clock remains readable without source/bootstrap |
| `test_criterion_3_restart_keeps_sqlite_obligations` | `ModuleNotFoundError: No module named 'kestrel.notifications'` | PASSED: reopening SQLite and a fresh CLI process retain all records without a workbook |
| `test_criterion_4_unknown_never_means_not_reportable` | `AssertionError: assert False is None`; fallback_72h supplied a guessed deadline | PASSED: N/blank/unknown are null plus explicit UNKNOWN, with no deadline |
| `test_criterion_5_delivery_retries_acknowledgement_are_not_dispositions` | Missing notification module/principal | PASSED: FAILED/retry and SENT/ack records survive reopening, case queue unchanged, obligation remains PENDING |
| `test_criterion_6_tenant_authorisation_for_read_and_update` | `ImportError: cannot import name 'create_notification_app'` | PASSED: no/invalid credentials 401, foreign/read-only updates 403, scoped writes/acks succeed; actor spoof rejected |

The same authorised read/update policy is additionally tested in the main API;
its unauthorised notification-counter leak failed before removal (**1 failed,
15 passed** in the first targeted follow-up run). Final detailed acceptance output:
**7 passed**, including both HTTP factories ([log](acceptance-green.txt)).

Two further calendar regressions were written and run before their fixes:
`test_calendar_local_due_date_must_stay_inside_controlled_coverage` and
`test_business_day_calendar_cannot_silently_assume_no_holidays`. Both initially
returned a deadline instead of None (**2 failed**, [red](calendar-red.txt)); after
requiring local due-date coverage and an explicit holiday list, **2 passed**
([green](calendar-green.txt)). No country-specific calendar was invented.

## Code inspection (distinct from execution)

- `notifications.NotificationObligations`: composite tenant/event SQLite records
  are loaded from ingested alerts before engine initialisation. Reads have no
  case-state/evidence join. Original alert origin is retained; re-ingestion cannot
  reset obligations. Existing UNRESOLVED statuses migrate to UNKNOWN without
  clearing references or moving the clock. Destructive reload of an ingested DB
  is refused, rather than erasing obligations.
- `notification_delivery_event` is a separate append-only SQLite log. Operator/
  adapter attempt claims, explicit retry intents and receipt references carry
  trusted actor attribution. Receipt references are UNVERIFIED; even an
  acknowledgement never makes the obligation FILED or removes it.
- `NotificationAccess` / `NotificationPrincipal` enforce explicit credential-
  digest grants and tenant read/write permissions on both HTTP factories. Missing
  configuration denies access. Foreign tenant/write checks precede record lookup.
  Unscoped notification counters were removed from the public health response.
- `regulatory_clock` uses null/UNKNOWN, not false or country/default-hour rules,
  when applicability/calendar authority is absent. `NotificationRule` is an
  explicit scoped arithmetic input contract, not an authenticated legal registry.
  It requires source/control references, coverage, timezone/cutoff and explicit
  business-day weekends/holidays; ambiguous/nonexistent DST cutoffs are refused.
- `engine`, domain models and `lifecycle.reopen` preserve nullable reportability.
  A full-suite failure exposed `False != None` on reopen; the bool coercion was
  fixed, not the existing test weakened ([first full run](full-first.txt)).
- API delivery POSTs only record claims. They never send messages, start workers,
  schedule retries or certify legal filing. Local CLI/DB methods are privileged
  filesystem/operator interfaces, not remote authentication boundaries.

## Executed verification

Environment: Python 3.13.5, `/tmp/fixvenv/bin/python`; confirmed import
`/workspace/kprod/src/kestrel/__init__.py` ([environment](environment.txt)).
The same fresh venv was used; no stale `/tmp/fv` installation was used.

Exact commands are in [commands.txt](commands.txt). Captured text/CSV copies normalise only trailing whitespace and line endings; original outputs remain in the temporary run directory. Actual final results:

- `pytest -o addopts='' -q`: **208 passed, 1 warning** in 28.23s ([full](full-green.txt)).
  Warning: Starlette's test-client/httpx deprecation; no adjudication failure.
- `ruff check`: **All checks passed!** ([log](ruff.txt)).
- `ruff format --check`: **62 files already formatted** ([log](format-check.txt)).
- `kestrel run-all` on fresh temporary DB/evidence/output paths: **420** persisted
  sample records ([summary](run-all.json), [CSV](verified.csv)).
- Full-result sealed-input replay: **420/420 identical**; all **8 tenant chains OK**
  ([verification](replay-and-chains.json)); CLI replay also identical and all 8
  CLI `verify` commands succeeded ([replay](cli-replay.json), [chains](cli-chains.jsonl)).
- Configured in-process notification API sample: authenticated tenant read 200,
  unauthenticated 401 ([actual EXC-107133 record](api-sample.json)). This is not
  production SSO or a live delivery test.

### Inspected counts and differences

Before and after, in AUTO_CLOSE / QA / note / quarantine / destroy order:
**0 / 290 / 0 / 0 / 0**, plus **130 historical candidates**. Verified closures **0**;
other unverified AUTO_CLOSE **0**. **No event changed recommendation**. These
remain stratified sample counts, not accuracy, legal-reportability or safety rates.
EXC-107133 remains QA.

The independent lane contains **28 conservative PENDING** records (historical Y)
and **392 UNKNOWN** records. No verified legal applicability is invented. All
**420 former inferred deadlines** became null/UNKNOWN because no approved
scope/calendar rules are supplied. The source flags/windows remain references;
the 420 affected IDs are in `deadline_changes` in the verification JSON. This
uncertainty is not permission to miss an obligation: qualified regulatory review
and a validated operational clock service are still needed.

### Existing tests changed

Only notification uncertainty expectations changed: the prior item-2 golden and
cross-pack invariant now assert the exact UNKNOWN term instead of UNRESOLVED.
The existing standalone HTTP test now provides explicit fixture credentials and
tenant read grants instead of endorsing unauthenticated access. Versions are
0.5.1 in package/config/domain/test settings. No disposition/count test was relaxed.
The original mismatch/stability/identity tests and counts are restored unchanged
from item 2 after abandoning uncommitted item-3 work.

## Remaining limitations / stop point

No approved legal-policy/calendar registry, authenticated authority/market/product
applicability adapter, live sending/retry worker, verified delivery/filing receipt
adapter, FILED transition or 24/7 pager is provided. Retry times are recorded
intent, not scheduled work; delivery acknowledgements are unverified references,
not filing proof. UNKNOWN records require human regulatory review. No actual
regulator or transport was contacted.

The credential-digest adapter needs deployment provisioning, rotation/revocation,
SSO and secret handling; none is validated here. Other case/evidence/dashboard API
routes still lack production authentication/role/dual-sign enforcement. Notification
local CLI/DB access assumes filesystem privileges; SQLite is not a demonstrated
production retention/availability/tenant-isolation deployment. Reference changes
are not an automatic legal-policy reconciliation/reclassification system.

Items **3–8 are not delivered**. Uncommitted identity work was reverted at the
user's scope change; previously committed item 2 is retained. No source docs or
clinical verification were invented. Work stops after commit, normal push and CI.
