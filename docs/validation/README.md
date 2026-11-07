# Current historical-candidate review: rule/code 0.4.3

These specific defects were addressed; overall safety and production readiness remain unvalidated.

[Executed report, test-first failures/passes, all 130 changed IDs, API/schema/UI/evidence and replay/chain results](historical-candidates-review/report.md).

Before: **130/290/0/0/0** in AUTO_CLOSE/QA/note/quarantine/destroy order. After: **0/290/0/0/0**, plus **130 HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED** (93 duplicate, 37 facility/no-product). Verified AUTO_CLOSE **0**, historical candidates **130**, other unverified AUTO_CLOSE **0** are always counted separately. Historical text remains reference, never independent duplicate/load verification. No production accuracy or count optimization is claimed.

---

## Historical 0.4.2 explicit-storage review

These specific defects were addressed; overall safety and production readiness remain unvalidated.

[Executed report, full 86-case table, outcome diff and AUTO_CLOSE path inventory](storage-limits-review/report.md). At 0.4.2 sample counts were **130/290/0/0/0** in AUTO_CLOSE/QA/note/quarantine/destroy order, versus **111/309/0/0/0** at 541202b. There are 35 changes: 27 QA→historical AUTO_CLOSE and 8 AUTO_CLOSE→QA for unresolved nominal cryogenic instructions. No production extrapolation or count optimisation.

The records below are retained historical validation, not current results.

---

# Historical correctness review: rule/code 0.4.1

[Full report, exact commands, test-first evidence and event-level diff](correctness-review/report.md). The new sample counts are **111/309/0/0/0** in AUTO_CLOSE/QA/note/quarantine/destroy order, versus **224/106/53/26/11** at fbf5322. Exactly 203 recommendations change, all to QA. No production accuracy is claimed. The source PDF/workbook are unchanged.

The records below and the existing `review-run-2026-11-07.json` / `outcome-changes-2026-11-07.json` are retained as **historical 0.4.0 validation**, not overwritten as if newly executed.

---

# Validation history — 7 Nov 2026 (CET)

`review-run-2026-11-07.json` records the reproduced software/sample regression baseline, not QA-approved clinical outcomes. The source workbook and PDF are unchanged. The 420 rows are a stratified evidence sample, not production volume.

## Reproduce

```bash
pip install -e ".[api,dev]"
make lint
make test
kestrel --db /tmp/kestrel-review/state.db --evidence-dir /tmp/kestrel-review/evidence run-all --out /tmp/kestrel-review/results.csv
kestrel --db /tmp/kestrel-review/state.db --evidence-dir /tmp/kestrel-review/evidence shadow-bulletin --out /tmp/kestrel-review/shadow.json
kestrel --db /tmp/kestrel-review/state.db --evidence-dir /tmp/kestrel-review/evidence agreement
```

For each run-all row, `AdjudicationService.replay_from_bundle(bundle_id, tenant_code)` was called: 420/420 full results identical, no new persisted artifacts. All eight tenant chains verified. New tests additionally remove live pack/engine objects before replay. No archived historical executable runtime or remote archive restore was tested.

## Focused regression tests

All under `tests/test_review_regressions.py`:

- Bound semantics: `test_bulletin_threshold_crossing_escalates_and_keeps_reported`, `test_bulletin_freeze_lower_bound_is_not_silently_released`, `test_bulletin_same_outcome_stays_flagged`, `test_unaffected_firmware_has_no_shift`.
- Parser: `test_qualified_prohibition_is_cap_not_unconditional_ban`, `test_unqualified_prohibition_remains_ban`, `test_qualified_cap_missing_duration_never_invents_release_or_destroy`.
- Identity/study scope: `test_unknown_tenant_fails_closed_even_for_historical_noise`, `test_duplicate_gtin_is_ambiguous_within_tenant`, `test_same_gtin_in_another_tenant_does_not_leak`, `test_study_reference_is_tenant_scoped`.
- Signing: `test_sign_requires_viewed_hash`, `test_sign_artifact_appears_in_basis_without_mutating_original`, `test_sign_rejects_tampered_bundle_even_with_matching_stored_hash`, `test_generic_transition_cannot_bypass_signature`.
- Replay: `test_replay_uses_sealed_inputs_after_live_pack_removed`, `test_replay_compares_full_result_and_rejects_other_versions`.
- Reopen: `test_reopen_preserves_deadline_reportability_and_prior_signature`.
- Shadow parameter: `test_shadow_custom_bound_drives_arithmetic`.

Existing API regression `test_sign_requires_named_signer_and_current_evidence` now also rejects omitted hash (422). Existing invariant `test_bulletin_preserves_reported_and_records_bound` verifies reported and upper scenario values across every affected sample event.

## Interpretation

Historical 0.4.0 counts in AUTO_CLOSE/escalation/note/quarantine/destroy order: **224/106/53/26/11** (old blanket-bias/parser baseline: 224/80/54/31/31). Shadow has 91 candidates and 91 scenario/evidence diffs but only **4 disposition flips** compared with reported-only evaluation. Historical-final agreement is 11/200 (5.5%); assistant-draft agreement203/420 (48.33%). These are not production safety/accuracy improvements. See the case-study limits for unimplemented evidence, workflow and operational requirements.

Compared with original production `ae2d84a`, exactly26 recommendations change, all to QA escalation:22 qualified-cap/incomplete-authority cases and4 temperature-uncertainty cases. Complete event-level diff is in `outcome-changes-2026-11-07.json`. The four uncertainty-sensitive events are EXC-110021,EXC-110413,EXC-110378 andEXC-110399. EXC-112289 andEXC-112842 both change DESTROY→QA; EXC-107133 andEXC-112198 retain their outcomes.
