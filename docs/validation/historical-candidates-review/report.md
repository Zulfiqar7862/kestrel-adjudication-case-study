# Historical closure candidates: executed review (0.4.3)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Repository: https://github.com/Zulfiqar7862/kestrel-adjudication-case-study

Base: `384b0c75fd09b51309c4e27b6ad4901c86907e35`; branch: `fix/correctness-review`. No merge, PR, main/production edits or force push. The commit containing this report is identified by `git rev-parse HEAD`; its normal push and CI result are reported after CI finishes. Run date: 7 Nov 2026 (CET). Python 3.13, existing fresh `/tmp/fixvenv`; [confirmed import](import-path.txt) is `/workspace/kprod/src/kestrel/__init__.py`, not the stale editable checkout.

## 1. Executed outcomes, not production accuracy

| Sample recommendation / metric | Before 0.4.2 | After 0.4.3 |
|---|---:|---:|
| AUTO_CLOSE recommendation | 130, all historical/unverified | 0 |
| HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED | 0 | 130 |
| ESCALATED_TO_SENIOR_QA | 290 | 290 |
| RELEASE_WITH_NOTE | 0 | 0 |
| QUARANTINE_PENDING_LAB | 0 | 0 |
| DESTROY | 0 | 0 |
| Independently verified closures | No separate old counter; no independent proof found | 0 |
| Other unverified numeric AUTO_CLOSE | No separate old counter | 0 |

Before requested five-count order: **130/290/0/0/0**. After: **0/290/0/0/0**, **plus 130 unresolved historical candidates**. These are all 420 sample rows, not closure KPIs or an accuracy estimate. No count target was optimized.

Exactly **130** recommendations changed: **93 duplicate**, **37 facility/no-product** historical labels, all AUTO_CLOSE → unresolved human review. [Every changed ID and reason](changed-events.json), [before CSV](before.csv), [after CSV](verified.csv), [run-all summary](verified-run.json). All 290 existing QA recommendations remain QA. The workbook has 220 historical closure-reference rows (107 duplicate, 43 facility, 40 sensor, 30 dock): the other 90 remain stopped by stronger evidence/authority gates. See [reference grouping](historical-reference-groups.json).

Historical-final agreement remains **4/200 (2%)**; assistant-draft agreement changes **130/420 (30.95%) → 0/420 (0%)** because review candidates are not AUTO_CLOSE recommendations. These are comparisons to unverified historical labels, not clinical validation. [Agreement](agreement.json). Firmware shadow: **91 candidates, 91 evidence/scenario diffs, 0 disposition flips** ([summary](shadow-summary.json)).

[Actual before/after full results](before-after-examples.json):

- **EXC-112198:** AUTO_CLOSE, historical duplicate → HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED, confidence 0, human review/signature required; case PENDING_EVIDENCE; no independent duplicate evidence.
- **EXC-112352:** AUTO_CLOSE, historical facility/no-product → the same unresolved review category; no verified load record.
- **EXC-107133:** QA → QA; unresolved study applicability/SOP authority unchanged. No attempt to match history.
- The prior 86 label-bound cases now have **27 unverified candidates, 59 QA, 0 AUTO_CLOSE**. Their raw text, parsed limits and deciding rules are rerun in [86-current.json](86-current.json). The 83 parsed/3 unresolved split is unchanged; no storage rules were changed in this task.

## 2. Test-first evidence and fixes

The initial **17 regression checks were written and executed before implementing the fix**: [original red log](historical-red.txt), **17 failed**. They then all passed: [first green log](historical-green-first.txt), **17 passed**. Four additional audit checks were added for later numeric/gateway bypasses and nonhistorical metric categorization; [final regression log](historical-green.txt) is **21 passed**. The expanded test file was also run retrospectively against an isolated archive of the pinned base; this is separate from, not a replacement for, the original test-first run (**21 failed** in [expanded baseline log](expanded-baseline-red.txt), [import proof](expanded-baseline-import.txt)).

All names below are in `tests/test_historical_candidates.py`:

| Regression | Observed original failure | Implemented fix | Observed passing contract |
|---|---|---|---|
| `test_historical_text_cannot_authorize_autoclose` (5 classifications × forged-verification flag false/true) | 10 × `AssertionError: assert 'AUTO_CLOSE' == 'HISTORICAL_C...TE_UNVERIFIED'` | `decision_rules.rule_duplicate_alert`, `rule_facility_equipment_event`, `rule_sensor_artefact`, `rule_dock_door` return explicit historical candidates, confidence 0; no invented verification flags accepted | All 10 return unresolved candidates and preserve “not independent” trace labels |
| `test_api_candidate_is_review_only_and_preserves_history` | AUTO_CLOSE instead of candidate | Shared `AdjudicationResult.closure_fields`, typed API responses, lifecycle PENDING_EVIDENCE | Candidate, raw historical text, human review/signature true, empty independent evidence; detail agrees |
| `test_openapi_declares_candidate_and_review_fields` | `assert '$ref' in {'additionalProperties': True, 'type': 'object', ...}` | API response models with Disposition/CaseState enums and explicit review/eligibility/evidence fields | Enum includes candidate; response schema declares all fields |
| `test_ui_renders_verified_and_historical_counts_separately` | Expected rendered `data-metric="verified-auto-close">0</strong>` absent | `/ui` server-rendered counts; separate badge/filter, raw-reference warning, no candidate final-sign form | Actual HTTP-rendered HTML shows 0 verified / 130 historical, plus candidate wiring/limitation labels |
| `test_evidence_keeps_reference_and_explicit_unresolved_status` | Sealed disposition AUTO_CLOSE | `engine.adjudicate` assessment and `service._persist` recommendation/reference records | Candidate and review fields sealed; raw alert classification retained; full replay identical |
| `test_metrics_and_run_all_never_fold_candidates_into_closures` | `KeyError: 'closure_counts'` | Shared `closure.closure_counts` in health/agreement/events/run-all | Each reports verified 0 / historical 130 / other-unverified 0; no sample row AUTO_CLOSE |
| `test_cli_outputs_explicit_candidate_fields_and_separate_counts` | CLI AUTO_CLOSE | Single and batch CLI JSON/CSV assessment fields and counters | Candidate JSON, 130 separate candidates, zero AUTO_CLOSE |
| `test_candidate_cannot_be_signed_or_auto_closed_as_if_verified` | `Failed: DID NOT RAISE TransitionError` on automatic closure | Lifecycle pending-evidence routing, candidate CLOSED_AUTO guard and non-final-category sign refusal | Direct and RECOMMENDED detour closure refused; candidate cannot itself be a signed final fate |
| Follow-up `test_historical_guard_blocks_later_numeric_autoclose` (3) | Retrospective pinned-base AUTO_CLOSE, not initial test-first checks | Final `decide` historical guard catches gateway/within-range fallback; stronger QA unchanged | Sensor artefact + gap, dock text without flag, alternate artifact spelling cannot escape to AUTO_CLOSE |
| Follow-up `test_numeric_rule_support_is_not_counted_as_independent_verification` | Pinned base has no closure metrics module | Third metric category prevents a numeric prototype AUTO_CLOSE label from being called independently verified | Rule-supported-but-unverified AUTO_CLOSE remains separate from candidate and verified counters |

Full-suite intermediate run: **9 failed, 177 passed** ([log](full-first.txt)); those failures were old expectations endorsing historical AUTO_CLOSE or old sample metrics. Final suite: **190 passed**, one Starlette/httpx deprecation warning, no skips. [Full log](full-tests.txt). No original tests were deleted or relaxed to accept multiple outcomes.

### Existing test changes and why

- `TestRuleOrder.test_first_verdict_wins`: historical duplicate before identity is now an **unresolved review candidate**, not closure authority. Its ordering expectation remains specific.
- `test_facility_equipment_event_auto_closes` renamed `test_facility_equipment_event_requires_review`: changes the expressly forbidden policy; now asserts the independent-load limitation.
- Four `test_storage_limits.test_historical_autoclose_has_explicit_unverified_provenance` cases renamed to `...candidate...`: strengthen previous label-only protection to **no AUTO_CLOSE**, keeping provenance assertions. Numerical parser/boundary expectations unchanged.
- `TestReviewerDashboard.test_ui_page_and_events`: after inspecting the real rerun, asserts zero AUTO_CLOSE and 130 separate candidates, rather than 130 closures.
- `TestAgreementAndHealth.test_agreement_report_headline`: actual assistant comparison is now 0/420; historical-final 4/200 unchanged.
- `test_health_report_has_alert_catalog`: actual mix now has zero AUTO_CLOSE and 130 candidates. Health's **sample regression baseline**, not clinical approval, updated from the observed run.
- `tests/_base.py` pins rule/code 0.4.3 for the changed bundle/replay semantics. No golden-case outcomes were changed.

## 3. Surfaces and sample API

[Executed full API JSON](sample-api.json), [OpenAPI](openapi.json), [evidence excerpt](sample-evidence-excerpt.json), [server-rendered UI count section](ui-render-summary.html):

```json
{
  "event_id": "EXC-112198",
  "recommendation": "HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED",
  "historical_classification": "NON_ACTIONABLE — duplicate of earlier alert",
  "closure_eligibility": "historical_candidate_unverified",
  "independent_closure_evidence": [],
  "requires_human_review": true,
  "requires_human_signature": true,
  "case_state": "PENDING_EVIDENCE"
}
```

The new recommendation is preferable to a generic QA reason because consumers cannot silently conflate the former 130 historical closures with either verified closure or ordinary product-fate recommendations. It is explicitly **review routing, not a final disposition**. Existing stronger QA remains QA. The raw historical classification remains in facts (`ExcursionFacts.event.triage_outcome`) and is copied into result/API/evidence fields; no historical record is rewritten.

Evidence stores it in `recommendation`, `inputs.alert.historical_classification`, `inputs.resolution.closure_assessment`, and the rule trace. The assessment names the historical source and absence of independent closure evidence. Run-all CSV/JSON, single CLI output, agreement/headline, health report and events/dashboard share the assessment and counters:

```json
{"verified_auto_close": 0, "historical_candidates_unverified": 130, "other_auto_close_unverified": 0}
```

AUTO_CLOSE **alone** never implies independent verification in these metrics. No current source/adapter emits independently verified eligibility; the third counter honestly retains any legacy numeric prototype closure separately rather than inventing verification.

## 4. Inspection findings: independent evidence and AUTO_CLOSE paths

**Source/code inspection, distinct from executed verification:** all 15 workbook-sheet headers, workbook README, queue/incident samples, all 420 event text fields and historical notes were inspected ([headers/source extract](data-inspection.txt), [full historical-note/cross-reference scan](closure-source-audit.txt)).

- No independent canonical duplicate-of event link, authoritative load manifest/empty-load attestation, authenticated sensor-artefact finding or exposure verification artifact is supplied. No other-event EXC-ID reference occurs in event text fields.
- Of 107 duplicate-classified rows, 11 have notes; of 43 facility rows, 25 have notes. These are controller-failure coincidence or reconstructed-gap text, not duplicate/load verification. Logger/shipment IDs and numerical summary flags are not empty-load evidence.
- Reviewer queue is derived from the same case rows (workbook README); reviewer action/timing is not an independent verification artifact. Incident INC-2502 establishes a controller-failure incident, not “no product loaded” for a specific alert.
- No verification adapter, boolean proof flag, dedup ledger or load ledger was invented. No independently verified closure can be demonstrated from these supplied data.

| Inspected path | Code semantics now | Executed 420-row count |
|---|---|---:|
| `rule_duplicate_alert` | Historical candidate; not independent duplicate verification | 93 candidates |
| `rule_facility_equipment_event` | Historical facility/no-load candidate; not independent load verification | 37 candidates |
| `rule_sensor_artefact` | Historical sensor candidate; near-limit heuristic is not verification | 0 candidates |
| `rule_dock_door` | Historical dock candidate; flag/duration not independent load/exposure verification | 0 candidates |
| final `rule_historical_closure_guard` | Converts later AUTO_CLOSE with recognized historical closure text to candidate; preserves prior QA | 0 candidates |
| `rule_gateway_gap` | Remaining AUTO_CLOSE path: supplied gap/interpolation summaries, not independently verified raw series | 0 AUTO_CLOSE |
| `rule_within_label_range` | Remaining AUTO_CLOSE path: numerical summaries within parsed limits; other restrictions/completeness unverified | 0 AUTO_CLOSE |
| `rule_stability_allowance` | Remaining AUTO_CLOSE path: single-event allowance prototype, still authority-gated | 0 AUTO_CLOSE |

[Executed rule inventory](rule-inventory.json). Zero sample emissions do **not** validate any coded path's general behavior. The final guard is exercised by the three synthetic follow-up tests, not by these sample rows. The 130 candidate classifications are not certified as fact.

## 5. Exact executed verification commands and results

All source-work/CI commands run from `/workspace/kprod`; runtime DBs, evidence and CSVs stay under `/tmp/kestrel-historical`. Source workbook/PDF unchanged. The existing fresh venv was reused, not `/tmp/fv`.

```bash
/tmp/fixvenv/bin/pip install -e '.[api,dev]'
/tmp/fixvenv/bin/python -c 'import kestrel, importlib.metadata; print(kestrel.__file__); print(kestrel.__version__); print(importlib.metadata.version("kestrel-sentinel"))'
# /workspace/kprod/src/kestrel/__init__.py; module/package 0.4.3

# At base, before code changes: 169 passed; original new regressions: 17 failed.
/tmp/fixvenv/bin/pytest -o addopts='' -q tests/test_historical_candidates.py
# After fix, expanded checks: 21 passed (also rerun with -v -o addopts='' for per-test PASS names).
/tmp/fixvenv/bin/pytest
# 190 passed; one Starlette/httpx deprecation warning.
/tmp/fixvenv/bin/ruff check .
# All checks passed!
/tmp/fixvenv/bin/ruff format --check .
# 56 files already formatted.

# Base capture at 384b0c7, before implementation:
/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/before.sqlite --evidence-dir /tmp/kestrel-historical/before-evidence --log-level WARNING run-all --out /tmp/kestrel-historical/before.csv
# 420; AUTO_CLOSE 130, QA 290.

# Final persisted rerun:
/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/verified.sqlite --evidence-dir /tmp/kestrel-historical/verified-evidence --log-level WARNING run-all --out /tmp/kestrel-historical/verified.csv
# 420; candidates 130, QA 290; closure_counts 0/130/0.
/tmp/fixvenv/bin/python docs/validation/historical-candidates-review/verify_run.py /tmp/kestrel-historical
# 420/420 identical full-result replays; 8/8 valid chains covering 420 bundles;
# 130 changed events; sample API HTTP 200 and PENDING_EVIDENCE; rendered UI counters.

/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/verified.sqlite --evidence-dir /tmp/kestrel-historical/verified-evidence --log-level WARNING replay --bundle EVB-b9394dd189b89986 --tenant T-AURA
# identical: true; candidate → same candidate.
# The same CLI prefix plus verify --tenant T was executed for every T in:
# T-AURA T-CAMPOS T-KAVERI T-MERIDIAN T-NORDIA T-PINNACLE T-SAHYADRI T-VIRENT
# all ok:true; lengths 33/26/44/16/28/26/83/164, sum 420.

/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/verified.sqlite --evidence-dir /tmp/kestrel-historical/verified-evidence --log-level WARNING agreement
/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/verified.sqlite --evidence-dir /tmp/kestrel-historical/verified-evidence --log-level WARNING health
/tmp/fixvenv/bin/kestrel --db /tmp/kestrel-historical/verified.sqlite --evidence-dir /tmp/kestrel-historical/verified-evidence --log-level WARNING shadow-bulletin --out /tmp/kestrel-historical/shadow.json
# Agreement 4/200 and 0/420; closure_counts 0/130/0; shadow 91/91/0.

git diff --check
# clean; normal commit/push, then gh run watch <run-id> --exit-status (reported after push).
```

[Baseline tests](baseline-tests.txt), [lint](lint.txt), [format](format.txt), [replay and chains](replay-and-chains.json), [summary](replay-verify-summary.json), [explicit CLI replay](cli-replay.json), [eight CLI chain checks](cli-chains.jsonl), [health](health.json). API samples use a **separate** temp `surfaces` DB, so they do not inflate the 420-bundle run's chain lengths. Retrospective expanded-baseline reproduction uses `git archive` into `/tmp/kestrel-historical/base` and an explicitly logged temporary PYTHONPATH; it does not switch or overwrite the working branch.

## 6. Remaining gaps

- There is no independent duplicate/load verification source or implemented evidence-attachment/verification adapter. Human review is required; candidate status is not a promise that closure will eventually be appropriate.
- Legacy **nonhistorical numeric AUTO_CLOSE** paths remain prototype summary/index heuristics (zero current sample outputs). They retain legacy no-signature behavior; metrics label them **other unverified**, never independently verified. This focused change does not certify or comprehensively redesign those paths.
- UI regression verifies actual **server-rendered HTTP HTML counts** plus candidate template/handler wiring. A real browser/JavaScript end-to-end session was **not** executed; do not claim browser interaction verification.
- Raw temperature series, authenticated sensor provenance, complete exposure history, authoritative SOP/site annexures and clinical study validation remain unavailable. Existing specific guards are not general clinical validation.
- Manual sign-off still uses a typed name, not authenticated/authorized or dual signatures; explicit reviewer overrides do not independently enforce missing clinical authority. A human may review a candidate but cannot finalize the candidate category itself.
- No live storm-control, paging, regulatory-calendar validation, seven-year object-lock durability, or cross-resource/concurrent-write guarantees were added. Hash/replay checks establish consistency of supplied records, not truth of those records.
- One dependency deprecation warning remains; no test was skipped to hide it. Older validation directories are explicitly historical snapshots, not current counts.

These specific defects were addressed; overall safety and production readiness remain unvalidated.
