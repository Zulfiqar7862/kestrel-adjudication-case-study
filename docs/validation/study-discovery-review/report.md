# Item 4 — study discovery with rejection reasons

Baseline: `15724a2df10b11e6a76c2ef32c4a59249434c226`, branch
`fix/correctness-review`. Scope is **only adoption-list item 4**. No merge, PR,
source-data edits, LLM, hard-coded study fix, or work on items 5–8.

## Source inspection and design boundary

Read the supplied brief PDF (especially the pen/vial/unreadable-study search and
site/SOP authority discussion) and actual workbook product/stability rows.
The index contains product text, tenant, study type, tested conditions/duration,
outcome, permitted text, filename, readability and indexing notes. It contains
**no study approval/effective/known/supersession metadata**, full study reports,
verified complete batch history, or governing SOP/annexure bodies. A file path,
"archive/old", an indexer's name, or a study merely existing is not that evidence.
No clinical rule or source assertion was manufactured to fill those gaps.
Claude's repository/code was not read or imported for this item.

The implemented search catalogues **all tenant-owned study index rows**, in source
order, with physical sheet/row provenance. It excludes foreign/unowned rows
before searching; a missing cited row is explicitly outside tenant scope (absent
or foreign, without disclosing another tenant's data). A defensive per-candidate
helper rejects/redacts wrong-tenant material. Replayed snapshots use the same
scope, so foreign existence is not needed to reproduce the result.

Every candidate has SELECTED/REJECTED state, cited flag and typed reasons carrying
code, detail and REJECTED/UNKNOWN assessment. Conservative product, strength/unit
and presentation checks never infer a synonym, strength conversion or an alternate
mapping. Duplicated citations cannot win by row order. Uncited studies are visible
but remain `UNCITED_MAPPING_UNKNOWN`, rather than being silently substituted.

Time/temperature coverage uses explicit permitted text and the affected-firmware
upper-bound scenario. A cumulative "above 8 C" threshold is not a maximum tested
temperature; absent lower-envelope/time limits remain unknown. Cumulative and
single-use language requires complete prior exposure rather than assuming zero.
Approval/effectivity/availability/supersession and SOP conflict/missing authority
are explicit blockers. Unknown conditions block clinical use, not just release.

Optional authority fields (`approval_status`, `effective_from/to`, `known_from`,
`superseded`) are **synthetic source-assertion inputs**, not workbook facts or a
new clinical policy. Tests exercise both a generic fully explicit selection and
rejection at missing/future/invalid dates. Missing endpoints do not imply an
open interval. Such assertions are not authenticated approvals or a historical
archive. The engine has no supplied governing SOP body and therefore never
claims an admissible study selection in the real sample.

## Evidence, API and UI

- `AdjudicationResult.study_discovery` equals sealed
  `inputs.resolution.stability.discovery` and `inputs.expected_result.study_discovery`.
- Typed event/adjudication models expose the catalogue; OpenAPI includes
  `StudyDiscovery`, `StudyCandidate`, `StudyRejection`, `StudyRejectionCode`.
- The UI explicitly distinguishes **cited** from **selected**, renders selected and
  rejected rows, provenance, codes/details/UNKNOWN, and escapes source text.
- A missing admissible selection marks study authority unresolved. The contextual
  `resolve()` parser is not an authority API; its cited ref is not a selection.
- [Actual API payload](api-EXC-107133.json), [OpenAPI components](openapi-study-components.json),
  [actual Node-rendered panel](ui-study-panel.html).

## Executed test-first evidence

[Commands](commands.txt); all commands ran in `/workspace/kprod` using
`/tmp/fixvenv`; import path was `/workspace/kprod/src/kestrel/__init__.py`.

| Regression cycle | Before implementation / hardening | Final result |
|---|---|---|
| Candidate selection/rejections, scope, identity/strength/presentation, duplicate citation, coverage, time, cumulative, evidence/API/UI | 38 failed with production source unchanged; [corrected red](red-corrected.txt) | All pass |
| Malformed dates, single-use wording, nonfinite measurements | 8 failed; 2 positive controls passed; [red](hardening-red.txt) | All pass |
| Cited typed rejection detail reaches engine rationale | 1 failed; 2 existing-arithmetic controls passed; [red](integration-red-final.txt) | Pass |
| Excel datetime metadata normalization | 1 failed; [red](date-red.txt) | Pass |
| Contradictory pen/PFS suffix hidden by parser precedence | 1 failed; [red](presentation-red.txt) | Pass |
| No selected study must not claim a selected cumulative assessment | 1 failed; [red](assessment-red.txt) | Pass |
| Final study suite | 50 red-backed cases plus 4 additional positive/conditional controls | **54 passed**, [output](green-final.txt) |
| Full suite | Initial integration: 3 failed /306 passed; [output](full-initial.txt) | **325 passed**, [output](pytest.txt) |

One pre-existing FastAPI/Starlette TestClient deprecation warning remains. Early
harness/import/CLI mistakes are disclosed in commands.txt; they are not counted
as successful acceptance failures or hidden as application regressions.

### Existing-test changes (not deleted, skipped or relaxed)

Two tests in `test_review_regressions.py` previously expected DESTROY from a
synthetic "No excursion permitted" index row lacking strength, approval, dates
and SOP authority. Retaining that expectation would violate this item's
requirement to leave unsupported authority unresolved. They now explicitly assert
QA, no selected study, `APPROVAL_UNKNOWN`, unchanged raw values, upper-bound
arithmetic and retained bulletin flags/sensitivity. This tightens the clinical
admissibility requirement; it does not introduce a new destruction/release rule.
Two added conditional-facts tests preserve the old freeze/prohibition arithmetic
below the discovery gate. No production decision-rule thresholds were changed.
The third initial failure's existing "no duration" assertion was preserved:
typed cited rejection details now reach the rationale and satisfy it.

## Executed sample, replay and counts

Fresh isolated SQLite/evidence run: [run-all](run-all.json),
[verification](verification.json), [actual CLI commands](executed-cli-commands.json).
All **420** records completed; **420/420 full-result replays identical**; all **8
 tenant evidence chains verified**. Direct CLI verify/replay also exited 0.
The final acceptance run used the reviewed source, including datetime,
contradictory-presentation and cumulative-wording fixes. All420 final objects
were recalculated against the baseline; [surface check](surface-validation.json). API/OpenAPI and sealed equality were executed with TestClient; UI
rendering/escaping was executed with Node, **not a browser end-to-end run**.

| Metric | Before (15724a2) | After |
|---|---:|---:|
| AUTO_CLOSE (including verified) | 0 | 0 |
| Senior QA | 383 | 383 |
| Historical candidates, unverified | 37 | 37 |
| Notifications PENDING | 28 | 28 |
| Notifications UNKNOWN | 392 | 392 |

No recommendations changed. No study was selected in the real sample, because
missing authority was not guessed. All 420 acquired a catalogue and trace;
exactly `study_discovery`, `evidence`, `rationale` differ at the top result level.
[Every affected event and its cited reasons](changed-events.md) (54 groups cover
all420), [all outcomes](all-outcomes.csv), [comparison](comparison.json).
No closure-count objective was used.

Ruff check/format passed. Documentation links and media were checked (see
[link report](links.json)). LLD/system design/validation/roadmap and affected
LLD/pipeline diagrams were updated; a study-discovery diagram was added.
Updated media/editable sources were copied to `/workspace/final-visuals`;
[copy hashes](visual-manifest.json). Generated diagram was visually inspected.

## Limits — inspection versus executed claims

**Executed**: the enumerated regression/suite/sample/replay/chain/CLI/API/OpenAPI/
Node rendering/link checks above. This does not constitute clinical validation.

**Inspected / still unvalidated**: authenticated full-report approvals, actual
historical study visibility or supersession, verified batch/once-only history,
governing site SOP/annexure content, alternate-study mapping curation, general API
tenant authentication, concurrency/load/residency/restore and independent
integrity anchors. Source assertions and heuristic text parsers are not qualified
clinical evidence. Literal strength comparisons can conservatively reject valid
unit equivalents; missing forms/synonyms remain unresolved. Current workbook
membership is not point-in-time availability. Version labels remain static settings,
not immutable source-code hashes; replay equality here is under the executed
current source, not proof of historical executable availability. No independent code-review agent
was available in this executor; final diff/self-inspection is not claimed as
independent review. Items 5–8 remain untouched.

Protected refs remain unchanged: main `745b457b380ba7f63b6f57ebe1bafa3e753db22a`,
production `fbf53227baf8aff2523d91b113065ef626bb7125`. The final response records
the normal-push commit and its actual CI result; no merge or PR is requested.

These specific defects were addressed; overall safety and production readiness remain unvalidated.
