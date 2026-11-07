# Explicit storage limits and AUTO_CLOSE provenance — 7 Nov 2026 (CET)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Repository: https://github.com/Zulfiqar7862/kestrel-adjudication-case-study

Branch: `fix/correctness-review`, starting at `541202b0ea12c1376d4b21d8e3f9503d693f14fe`; no merge, PR or production/main changes. Rule/code/package version is **0.4.2**. This report belongs to the correction commit; `git rev-parse HEAD` gives its full SHA. CI is watched separately after pushing.

## 1. Test-first changes and observed results

The original **123 tests passed** at the starting version ([baseline](baseline-tests.txt)). New specifications were written before implementation: the first run had **30 failed, 14 passed** ([original red output](storage-red.txt)). They demonstrated unparsed valid ranges, invented LN2 bounds, rejected one-sided evidence, absent explicit metadata and missing historical-classification labels.

| Added regression family in `tests/test_storage_limits.py` | Observed failure before fix | Implementation | Final verification |
|---|---|---|---|
| `test_storage_spelling_without_invented_bounds` | `2°C – 8°C` and signed/unit-bearing pairs returned unknown; nominal LN2 invented −196/−150; explicit ≤ −150 did not retain an upper-only meaning | `rules/as_of.py::parse_storage_limits`, `TemperatureBound`, `StorageLimits`; legacy numeric wrapper delegates to parser | All 9 cases pass |
| `test_explicit_bound_metadata` | Explicit metadata API absent | Each bound records kind, value and inclusive/strict flag; overall type is two-sided/upper-only/lower-only/unresolved | All 4 cases pass |
| `test_equality_and_strictness_at_each_boundary` | Valid upper-only/lower-only cases could not AUTO_CLOSE under the old both-bounds guard | `decision_rules.is_out_of_range` compares stated boundaries without inventing absent bounds; `ExcursionFacts.limits` carries the explicit semantics | All 11 cases pass: two-sided equality/violations, strict upper/lower equality, inclusive upper/lower equality, and upper-only with min absent |
| `test_missing_required_or_invalid_measurements_are_not_safety_evidence` | Positive regression controls retained the evidence guard | `temperature_measurement_issue` and first rule distinguish missing required extrema, nonfinite and reversed values. Upper-only requires max, lower-only requires min; mean is never a substitute | All 7 cases pass, including historical duplicate text with max absent and mean/min present |
| `test_malformed_or_ambiguous_storage_is_distinct_from_missing_measurements` | Wrong reason or closure on malformed/unclear text | New `rule_unresolved_storage` precedes historical classification; no CRT/nominal cryogenic numeric defaults | All 8 cases pass |
| `test_extra_constraints_are_preserved_without_becoming_numeric_bounds` | No structured independent-constraint representation | Parser preserves do-not-freeze, protect-from-light and other recognised annotations separately; engine/trace marks them not independently verified | Pass; no invented zero/lower bound |
| `test_historical_autoclose_has_explicit_unverified_provenance` | All 4 paths lacked the requested label | `AUTO_CLOSE_PATH_LIMITATIONS`, final trace entry and `engine.evidence.decision` identify unverified historical classification, not independent verification | All 4 duplicate/facility/sensor/dock cases pass; outcomes unchanged solely by adding labels |
| `test_decimal_comma_is_not_silently_a_two_sided_range` | `assert 'two_sided' == 'unresolved'` ([red](comma-red.txt)) | Comma tuples only recognised with explicit FROZEN tuple context | Pass |
| `test_unitless_one_sided_instruction_is_not_assumed_celsius` | `assert 'upper_only' == 'unresolved'` for “Below 25” ([red](unitless-red.txt)) | Newly recognised one-sided instructions require an explicit Celsius unit | Pass |

Final new suite: **46 passed in 0.11s** ([green](storage-green.txt)). Full suite: **169 passed, 1 dependency deprecation warning in 15.43s** ([log](full-tests.txt)). Ruff check and format check passed ([lint](lint.txt), [format](format.txt)).

Fixture transparency: boundary tests intentionally omit study authority so an out-of-range event routes to QA, rather than testing a clinical fate. An unrelated missing cited-study reference initially invoked the existing unreadable-study quarantine rule even for an in-range event; the range-only fixture was corrected to have no citation. Assertions were not weakened. Re-running the final 44-case core specification against an archived, unmodified starting-version source tree gave **29 failed, 15 passed** ([baseline-final-fixture red](storage-base-final-tests-red.txt)); the subsequent comma/unitless tests have their own red logs. The [first full-suite run](full-first.txt) preserves failures rather than concealing stale count/reason/trace expectations.

Existing tests changed only as follows: API/ops expected AUTO_CLOSE and assistant-agreement counts follow the inspected run; the Whitefield golden still requires QA but now requires the accurate **storage instructions unresolved** reason; the lane trace still requires “prior excursions” but searches the whole trace because decision/provenance entries now follow it. `_base.py` uses version 0.4.2. No case was forced to agree with history.

## 2. Code inspection: what now distinguishes the three cases

- Missing/invalid measurements: a supplied nonfinite extremum, reversed min/max, no extrema, or an absent required min/max produces `rule_insufficient_temperature`. Neither mean nor historical triage can waive it.
- Unparseable instructions: valid supplied measurements do not establish an unknown label. `rule_unresolved_storage` returns QA with an explicit reason; it is not mislabelled missing temperature data.
- Established one-sided limits: “Below 25 C” is upper-only **<25**; “≤ −150 °C” is upper-only **≤−150**. No lower bound is manufactured. Two-sided “2–8°C” has inclusive bounds. Opposite-sided examples also preserve strictness/inclusivity.

The grammar is deliberately limited, not an NLP resolver. Bare controlled-room-temperature prose lacks an approved numeric definition. Nominal cryogenic values are not governing limits. Unknown remaining clauses stay unresolved. Existing explicit unitless two-sided workbook shorthands retain their field-specific Celsius convention; this is a compatibility assumption, not a general permission to infer units. New one-sided text without a Celsius unit stays unresolved. Recognised extra restrictions are retained **but not independently verified**; no freezing point, light-exposure proof or new clinical rule was invented.

`engine.adjudicate` records the parsed metadata, actual deciding rule and AUTO_CLOSE limitation in the evidence and rationale. Same-version replay reproduces these records. The changes do not implement source validation or universal release authority.

## 3. Executed rerun of the 86 label-bound cases

Full event-by-event table: **[86-case-table.md](86-case-table.md)**. Machine-readable raw storage text, complete parsed metadata, reason, outcome, deciding rule and rationale: **[86-after.json](86-after.json)**. Previous outputs: [86-before.json](86-before.json).

| Raw storage text | Count | Parsed meaning | AUTO_CLOSE | QA |
|---|---:|---|---:|---:|
| `15°C to 25°C (excursions to 30°C permitted, see stability)` | 26 | Inclusive 15–25; excursion reference retained separately, not a new label bound | 9 | 17 |
| `2°C – 8°C` | 23 | Inclusive 2–8 | 7 | 16 |
| `-80C to -60C (dry ice permitted)` | 16 | Inclusive −80 to −60; dry-ice restriction retained separately | 3 | 13 |
| `Store below 25 C` | 10 | Upper-only, strictly <25; no lower bound | 5 | 5 |
| `-80 to -60 °C` | 7 | Inclusive −80 to −60 | 3 | 4 |
| `Controlled room temperature` | 3 | Unresolved: no explicit governing numerical limits/approved definition | 0 | 3 |
| `FROZEN (-25,-15)` | 1 | Explicit frozen tuple: inclusive −25 to −15 | 0 | 1 |
| Total | 86 | 83 parsed, 3 unresolved | 27 | 59 |

Still unresolved storage: **EXC-111008, EXC-110035, EXC-112149**. All have plain “Controlled room temperature”; no numerical policy is supplied. The other **56** QA cases now have parsed limits but remain blocked by study/SOP/presentation/uncertainty authority. All **27** new AUTO_CLOSEs are historical classification: **20 duplicate, 7 facility**. They are not independently verified duplicate/no-product events and are not evidence of universally safe closure.

## 4. Every AUTO_CLOSE path: inspection versus execution

Code inspection found seven emitting paths; full [path inventory](autoclose-paths.md). Executed sample results and per-event stored labels are in [autoclose-inventory.json](autoclose-inventory.json).

| Path | Actual sample count | Limitation |
|---|---:|---|
| `rule_duplicate_alert` | 93 | **Unverified historical classification**, not independent duplicate verification |
| `rule_facility_equipment_event` | 37 | **Unverified historical classification**, not independent load/no-product verification |
| `rule_sensor_artefact` | 0 | Historical classification + near-limit heuristic; no independent sensor verification |
| `rule_dock_door` | 0 | Historical classification + provided flag/duration heuristic; no independent load/exposure verification |
| `rule_gateway_gap` | 0 | Provided interpolation/gap summaries; no independent raw-series proof |
| `rule_within_label_range` | 0 | Temperature summaries only; raw-series completeness and extra restrictions unverified |
| `rule_stability_allowance` | 0 | Indexed single-event allowance candidate; final governing-authority gate still applies |

Executed assertions confirmed **all 130** sample AUTO_CLOSEs have the unverified historical-classification limitation stored in evidence. No outcome changed merely because the label was added. Code inspection also confirms existing AUTO_CLOSE handling still marks no signature required and persists `TRIAGED_NON_ACTIONABLE` through `CaseLifecycle.create`, not a final signed product release. The zero-count paths remain present; this sample does not establish their general safety.

## 5. Counts and exact changed events

Order: AUTO_CLOSE / QA / RELEASE_WITH_NOTE / QUARANTINE_PENDING_LAB / DESTROY.

**Before 111/309/0/0/0 → after 130/290/0/0/0.**

There are **35 changes**, not merely a net change of 19: **27 QA→AUTO_CLOSE** after recovering established bounds, and **8 AUTO_CLOSE→QA** because prior nominal cryogenic interpretation invented governing limits. See [all event-level changes and rationales](outcome-changes.json), [before CSV](before.csv), [after CSV](final.csv) and [summary](summary.json).

- `rule_duplicate_alert` (20): EXC-112506, EXC-112772, EXC-110735, EXC-112835, EXC-112226, EXC-112681, EXC-112499, EXC-110819, EXC-111708, EXC-111491, EXC-111351, EXC-112639, EXC-112464, EXC-111155, EXC-111134, EXC-110987, EXC-111904, EXC-112310, EXC-110826, EXC-112562.

- `rule_facility_equipment_event` (7): EXC-112352, EXC-111995, EXC-110854, EXC-110980, EXC-111820, EXC-111743, EXC-110833.

- `rule_unresolved_storage` (8): EXC-110770, EXC-111862, EXC-111106, EXC-111183, EXC-111456, EXC-110812, EXC-112534, EXC-112779.

The eight new QA cases have “LN2 vapour phase (-196 nominal)” (seven) or “Cryogenic, vapour phase only” (one). Neither text states governing numerical limits. No auto-close target was used. Historical-final comparison remains 4/200 (2%); assistant-draft comparison is 130/420 (30.95%). Shadow remains 91 candidates, 91 scenario/evidence diffs and 0 disposition flips. These are stratified-sample software results, not production accuracy or an assumption that historical decisions are correct.

## 6. Exact executed commands and verification

Working directory: `/workspace/kprod`; stayed on `fix/correctness-review` throughout. Existing fresh venv import reconfirmed:

```bash
/tmp/fixvenv/bin/python -c 'import kestrel; print(kestrel.__file__)'
# /workspace/kprod/src/kestrel/__init__.py
/tmp/fixvenv/bin/pytest -o addopts='' -q tests/test_storage_limits.py
# Initial red: 30 failed, 14 passed; final green: 46 passed
/tmp/fixvenv/bin/pytest -o addopts='' -q
# Final: 169 passed, 1 warning in 15.43s
/tmp/fixvenv/bin/ruff check .
/tmp/fixvenv/bin/ruff format --check .
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-one-sided/final2.sqlite --evidence-dir /tmp/kestrel-one-sided/final2-evidence run-all --out /tmp/kestrel-one-sided/final2.csv
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-one-sided/final2.sqlite --evidence-dir /tmp/kestrel-one-sided/final2-evidence agreement
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-one-sided/final2.sqlite --evidence-dir /tmp/kestrel-one-sided/final2-evidence shadow-bulletin --out /tmp/kestrel-one-sided/final-shadow.json
```

Additional red commands actually executed:

```bash
/tmp/fixvenv/bin/pytest -o addopts='' -q tests/test_storage_limits.py::test_decimal_comma_is_not_silently_a_two_sided_range
/tmp/fixvenv/bin/pytest -o addopts='' -q tests/test_storage_limits.py::test_unitless_one_sided_instruction_is_not_assumed_celsius
```

Their full observed failures are linked above. The archived-baseline confirmation used `git archive 541202b...` into a temporary directory, then `PYTHONPATH=/tmp/kestrel-label-baseline/src:/tmp/kestrel-label-baseline` and pytest `--import-mode=importlib`; its log records the baseline import path. It did not switch or modify a branch.

Replay/chain script iterated all 420 rows from the saved CSV, called `AdjudicationService.replay_from_bundle(bundle_id, tenant_code)`, asserted every `identical` result, and called `EvidenceStore.verify_chain` for each tenant. **420/420 full results identical; 8/8 chains verified** ([actual output](replay-chains.json)). No live workbook/engine was substituted for sealed replay inputs. These are local same-version integrity/reproducibility checks, not independent source/clinical validation or seven-year archive restore.

Reproduce the replay/chain verification against the saved temporary run:

```bash
/tmp/fixvenv/bin/python - <<'PYVERIFY'
import csv
from pathlib import Path
from kestrel.config import Settings
from kestrel.service import AdjudicationService
svc = AdjudicationService(Settings(
    db_path=Path('/tmp/kestrel-one-sided/final2.sqlite'),
    evidence_dir=Path('/tmp/kestrel-one-sided/final2-evidence'), log_level='WARNING'))
svc.bootstrap()
rows = list(csv.DictReader(open('/tmp/kestrel-one-sided/final2.csv')))
assert len(rows) == 420
assert all(svc.replay_from_bundle(r['bundle_id'], r['tenant_code'])['identical'] for r in rows)
tenants = {r['tenant_code'] for r in rows}
assert len(tenants) == 8
assert all(svc.evidence.verify_chain(t)['ok'] for t in tenants)
print('420 identical replays; 8 verified tenant chains')
PYVERIFY
```

README/current docs/expected sample baseline were updated only after inspecting executed results and the event diff. Old 0.4.0/0.4.1 validation records remain labelled historical. Logs/CSVs have only line endings/trailing whitespace normalized for Git; the source PDF/workbook were unchanged; only temporary SQLite/evidence runtime stores were used, and none were committed.

## 7. Remaining gaps

The parser is a limited explicit grammar, not general clinical interpretation. Unknown policies need a named reviewer. Additional restrictions are retained but not verified; full raw-series completeness, sensor applicability and product mapping are not independently established. Historical classification remains unverified, including all sample AUTO_CLOSEs. SOP bodies/site annexures, study validity dates, verified batch/once-only history, authenticated/dual signers, tenant contractual enforcement, independent duplicate/load proof and production notification calendars remain missing. Manual signing still does not independently enforce study/SOP clearance. Existing heuristic rules and endpoint firmware analysis are not universal safety proofs.

These specific defects were addressed; overall safety and production readiness remain unvalidated.
