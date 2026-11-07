# Focused correctness review — executed 7 Nov 2026 (CET)

Repository: https://github.com/Zulfiqar7862/kestrel-adjudication-case-study

Base: `fbf53227baf8aff2523d91b113065ef626bb7125`. Fix branch: `fix/correctness-review`. No merge into production/main. Rule/code/package version: **0.4.1**, so new semantics are not labelled 0.4.0. This report is part of the fixing commit; use `git rev-parse HEAD` for its full SHA. CI is checked separately after pushing.

## Test-first evidence

Stored logs/CSVs have line endings and trailing whitespace normalized only; results are unchanged.

Each issue's regression tests were written and run **before its implementation change**. The other fixes already made were retained between issues. Unmodified baseline ran all 67 existing tests successfully ([baseline log](baseline-tests.txt)); a fresh editable installation imported `/workspace/kprod/src/kestrel/__init__.py`, not the stale install elsewhere on the box.

| Bug → regression in `tests/test_correctness_review.py` | Observed red result | Fix | Observed final green |
|---|---|---|---|
| Missing/incomplete temperatures → `test_incomplete_temperature_range_is_unknown`, `test_missing_temperatures_cannot_be_bypassed_by_triage` | 15 failures: `assert False is None`; `assert 'AUTO_CLOSE' == 'ESCALATED_TO_SENIOR_QA'` ([red](01-temperature-red.txt)) | `decision_rules.is_out_of_range`: tri-state unknown; `rule_insufficient_temperature`: first gate, rejects absent/nonfinite/reversed extrema or unknown/invalid label bounds. No triage-text exemption. | 21 temperature/extrema checks pass ([log](01-final-green.txt)). |
| Carrier legal identity → `test_afx_de_exact_alias_beats_indian_substring`, `test_carrier_ambiguous_alias_is_unresolved`, `test_carrier_exact_legal_entity_beats_alias` | 3 failures; AFX-DE gave `CNT-2021-0118` instead of `CNT-2023-0441`; ambiguity returned a row ([red](02-carrier-red.txt)) | `IdentityResolver.resolve_carrier_contract`: active-date filtering, unique exact legal entity → exact alias → unique substring; explicit ambiguity, no name-length tie-break. Engine preserves unresolved error/rationale. | 6 carrier regressions pass; all 3 existing identity tests, including Tapti, pass ([logs](02-final-green.txt), [existing](02-existing-identity-green.txt)). |
| Full lifetime budget assumed → `test_cumulative_history_unresolved_before_earlier_rules` | 8 failures: RELEASE_WITH_NOTE or AUTO_CLOSE instead of QA ([red](03-cumulative-red.txt)) | `decision_rules.rule_cumulative_history_unresolved` precedes triage/gap rules; standalone allowance rule also checks it. Explicit unresolved assessment in engine evidence. No ledger, no zero-history assumption, no trust in arbitrary event fields. | 9 cumulative checks pass ([log](03-final-green.txt)). |
| Unestablished study/SOP authority → `test_mismatched_study_never_uses_master_allowance`, `test_study_applicability_must_be_established`, `test_sop_overlap_blocks_release_even_with_otherwise_usable_evidence`, `test_engine_sop_authority_blocks_early_gap_release`, `test_exc_107133_not_forced_to_history` | 11 failures: master/index sources accepted invalid applicability; gap/fallback paths released despite absent SOP/annexure or overlap ([red](04-authority-red.txt)) | `StabilityResolver.resolve`: unique tenant citation, product/presentation/type/readability checks, no master substitution or uncited alternate guess. `rule_stability_authority`: unresolved excursion → QA. `engine.adjudicate`: indexed SOP candidate is not governing site authority. `decision_rules.decide`: final release/allowance-closure authority gate covers **all** rule paths. | 20 study/SOP/final-gate checks pass, including all four release/allowance paths under missing SOP and overlap ([log](04-final-green.txt)). |

All **56** new parametrized regression cases pass ([log](all-regressions-green.txt)). Intermediate full-suite runs were executed after each issue; [01](01-full.txt), [02](02-full.txt), [03](03-full.txt), [04](04-full.txt) retain their failures rather than hiding stale golden expectations. Counts/goldens were not changed until inspecting the actual sample run and outcome diff. At issue 4, EXC-107133 was already QA because issue 3 blocked the master cumulative allowance; its still-failing assertion checked the forbidden master source, not a forced historical outcome.

## Actual before/after outputs

Complete observed records: [before](regressions-before.json), [after](regressions-after.json); [original EXC-107133 CLI](before-case.json), [corrected CLI](final-case.json). QA below means ESCALATED_TO_SENIOR_QA.

| Input/probe | At base | After |
|---|---|---|
| EXC-107133, unchanged workbook row | RELEASE_WITH_NOTE, confidence 0.8; mismatched study bypassed with master prose | QA, confidence 0; source unresolved; governing site/SOP unresolved |
| EXC-107133 with min/max/mean absent, triage cleared | AUTO_CLOSE | QA: insufficient temperature evidence |
| EXC-107133 missing min, duplicate triage | AUTO_CLOSE | QA: insufficient temperature evidence |
| EXC-107133 missing max, gateway gap/interpolation | AUTO_CLOSE | QA: insufficient temperature evidence |
| All 12 missing-extrema × triage combinations | AUTO_CLOSE | QA (parameter-level outputs in red/green logs) |
| AFX-DE, 2026-07-28 | Indian CNT-2021-0118 | German CNT-2023-0441 |
| Tapti Exp Cargo, same date | CNT-2021-0245 | CNT-2021-0245 |
| AFX, same date (exact Indian alias) | CNT-2021-0118 | CNT-2021-0118 |
| Two contracts claim same exact alias | Guessed one row | Explicit unresolved ambiguity |
| Exact legal entity competing with another row's alias | Wrong alias row | Exact legal entity row |
| Cumulative 72h, 15-minute event, no verified history | RELEASE_WITH_NOTE | QA, remaining allowance unknown |
| Cumulative allowance + gap | RELEASE_WITH_NOTE | QA; gap cannot bypass cumulative guard |
| Cumulative + duplicate/facility triage (4 parameter cases) | AUTO_CLOSE | QA |
| Missing/wrong-product/wrong-type/unknown-presentation/duplicate-reference study | Master or index allowance accepted | Unresolved, no parsed allowance (all 5 parameter cases) |
| Mismatched study with master text | Master fallback | Unresolved; no fallback |
| SOP overlap + brief mild event | RELEASE_WITH_NOTE | QA |
| Missing SOP / indexed site-annexure / revision overlap + early gateway path | RELEASE_WITH_NOTE in each | QA in each |

Missing mean **alone** is not insufficient for the implemented extrema-based range check when min/max are complete. No historical duplicate/no-product text is accepted as an exception to missing extrema/label bounds. A genuinely independently verified non-temperature closure channel was **not** invented.

## Executed commands and results

Working directory `/workspace/kprod`; first attempted `python -m venv` failed because the box has `python3`, not `python`. Successful setup:

```bash
git switch -c fix/correctness-review fbf53227baf8aff2523d91b113065ef626bb7125
python3 -m venv /tmp/fixvenv
/tmp/fixvenv/bin/pip install -e '.[api,dev]'
/tmp/fixvenv/bin/python -c 'import kestrel; print(kestrel.__file__)'
```

Red commands, executed before the respective fixes (nonzero exits preserved in linked logs):

```bash
/tmp/fixvenv/bin/pytest -q tests/test_correctness_review.py
/tmp/fixvenv/bin/pytest -q tests/test_correctness_review.py -k 'carrier or afx'
/tmp/fixvenv/bin/pytest -q tests/test_correctness_review.py -k cumulative
/tmp/fixvenv/bin/pytest -q tests/test_correctness_review.py -k 'study or sop or 107133'
```

Final commands actually executed:

```bash
/tmp/fixvenv/bin/pytest -o addopts='' -q
/tmp/fixvenv/bin/ruff check .
/tmp/fixvenv/bin/ruff format --check .
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-correctness/verified.sqlite --evidence-dir /tmp/kestrel-correctness/verified-evidence run-all --out /tmp/kestrel-correctness/verified.csv
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-correctness/verified.sqlite --evidence-dir /tmp/kestrel-correctness/verified-evidence adjudicate --event EXC-107133
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-correctness/verified.sqlite --evidence-dir /tmp/kestrel-correctness/verified-evidence agreement
/tmp/fixvenv/bin/kestrel --log-level WARNING --db /tmp/kestrel-correctness/verified.sqlite --evidence-dir /tmp/kestrel-correctness/verified-evidence shadow-bulletin --out /tmp/kestrel-correctness/final-shadow.json
```

Results: **123 passed, 1 dependency deprecation warning, 16.62s** ([pytest](full-tests.txt)); ruff check passed and format check passed ([lint](lint.txt), [format](format.txt)). Additional script calls to `replay_from_bundle(bundle_id, tenant_code)` for every saved CSV row returned **420/420 identical full results**, and `EvidenceStore.verify_chain` passed for **8/8 tenant chains** ([output](final-replays.json)). These are same-version local replay/integrity checks, not an archival restore or a clinical validation. Fresh temp DB/evidence/output paths were used; no runtime artifacts were committed.

## Inspected sample diff, then updated expectations

| Recommendation | Base | Corrected |
|---|---:|---:|
| AUTO_CLOSE | 224 | 111 |
| ESCALATED_TO_SENIOR_QA | 106 | 309 |
| RELEASE_WITH_NOTE | 53 | 0 |
| QUARANTINE_PENDING_LAB | 26 | 0 |
| DESTROY | 11 | 0 |

Exactly **203** events changed, all to QA: **86** insufficient/unresolved label-bound checks, **80** unestablished study applicability, **13** cumulative history, **24** final release authority. All event IDs, old/new outcomes and actual rationales are in [outcome-changes.json](outcome-changes.json), with [before CSV](before.csv) and [after CSV](verified.csv). The 86 temperature-evidence changes are **not** claims of missing sample temperatures: all had min/max, but 76 had no parseable label bounds and 10 lacked a lower bound. The guard deliberately treats unknown/one-sided label applicability as unresolved rather than assuming a complete safe range.

Shadow: 91 candidates, 91 scenario/evidence diffs, **0 flips**. Historical-final agreement **4/200 (2%)**; assistant draft **111/420 (26.43%)**. [Agreement](final-agreement.json), [shadow](final-shadow-summary.json), [run](final-run.json), [summary](summary.json). No extrapolation from this stratified sample, no claim of production accuracy/safety and no assumption that historical finals are correct. Adjudication outputs are computed by rules; only expected-count tests and the explicitly labelled health **sample baseline** are fixed numbers updated from this run.

Existing test changes, not weakened assertions:

- `test_decision_rules.py`: missing-range assertion now requires unknown; first-rule assertion requires the evidence guard; master mismatch now must escalate; cumulative full-budget release now must escalate; SOP-overlap test renamed to describe its trace-only helper. Temperature-only fixture explicitly isolates SOP authority, while engine/final-gate regressions exercise missing authority.
- `test_golden.py`: EXC-107133 must escalate; evidence/GTIN/signature/measurement checks remain. First Whitefield fixture must escalate because label bounds are unavailable; historical facility text cannot waive the guard.
- `test_api.py`, `test_ops.py`: exact outcome/count/agreement expectations updated only from inspected runs; EXC-107133 explicitly no longer agrees with history. Other API/isolation/replay checks retained.
- `test_review_regressions.py`: synthetic firmware/parser fixture now supplies a cited applicable excursion study rather than relying on prohibited master fallback. Its substantive firmware and cap expectations remain unchanged. A cross-tenant missing study is explicitly unresolved, not the old `none` label.
- `_base.py` plus runtime/package/domain defaults use version 0.4.1 to identify changed semantics.

## Inspection findings and remaining limitations

Code inspection confirms: no ledger/integration/clinical rules invented; no hard-coded STB-2738 selection; no longest-name tie-break; SOP conflicts cannot authorise engine release; original source PDF/workbook unchanged. Executed results establish the software/sample contracts above, **not** verified clinical applicability of workbook records.

The system still lacks authenticated signers/independent dual signing, source-document/raw-series archive, verified product aliases, study validity dates, batch/once-only-use history, authoritative site mappings, tenant-contract enforcement and notification calendars. Study matching is deliberately strict textual evidence over a curated index, not validated clinical resolution. SOP contents are absent, so it fails closed rather than resolving them. One-sided/unparseable label ranges conservatively need QA. Complete-data historical noise triage still lacks independent live duplicate/no-product proof; manual sign-off still does not independently enforce study/SOP clearance. Existing heuristic disposition rules remain prototype logic. None of those gaps were silently claimed fixed, and production/main remain unmerged.
