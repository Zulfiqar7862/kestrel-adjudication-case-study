# Decision rules (0.4.3)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Fixed rules produce prototype recommendations. `decision_rules.decide` records the actual deciding function and an explicit limitation for every AUTO_CLOSE.

## Ordered guards and authority

1. `rule_insufficient_temperature`: missing required max/min, nonfinite or reversed supplied extrema → QA. Required extrema depend on the explicit bound type; mean cannot substitute.
2. `rule_unresolved_storage`: absent, malformed or unclear governing storage bounds → QA, separately from measurement insufficiency.
3. `rule_cumulative_history_unresolved`: cumulative excursion with unavailable verified batch/history → QA, before historical triage. No zero-history assumption.
4. Historical duplicate/facility/sensor/dock classifications return unresolved review candidates, not AUTO_CLOSE. Existing stronger QA guards retain precedence. Remaining temperature/stability rules run in their prior order. `rule_stability_authority` rejects an excursion with unestablished cited-study applicability.
5. Final `rule_release_authority_gate` blocks release recommendations and allowance-based closures on unresolved study/SOP/site/annexure/overlap authority.

The numeric parser supports explicit inclusive pairs, strict/inclusive upper-only and lower-only bounds. “Below 25 C” does **not** imply a lower bound; “≤ −150 C” does **not** imply −196 C. Plain “controlled room temperature”, nominal cryogenic descriptions and unknown residual clauses remain unresolved. Extra restrictions are retained separately and marked not independently verified, not converted into invented numeric limits.

## Closure path inventory: inspected code versus executed sample

| Function | Current recommendation / limitation | Executed sample |
|---|---|---:|
| `rule_duplicate_alert` | Unverified historical candidate; no independent canonical-event duplicate link | 93 candidates |
| `rule_facility_equipment_event` | Unverified historical candidate; no independent load/no-product record | 37 candidates |
| `rule_sensor_artefact` | Unverified historical candidate; near-limit summaries are not sensor verification | 0 candidates |
| `rule_dock_door` | Unverified historical candidate; flag/duration is not load/exposure verification | 0 candidates |
| final `rule_historical_closure_guard` | Converts later AUTO_CLOSE on any recognized historical closure label to unresolved review; stronger QA remains QA | 0 candidates |
| `rule_gateway_gap` | Legacy numeric AUTO_CLOSE path; gap/interpolation summaries, not independent raw-series verification | 0 AUTO_CLOSE |
| `rule_within_label_range` | Legacy numeric AUTO_CLOSE path; supplied extrema satisfy parsed bounds only | 0 AUTO_CLOSE |
| `rule_stability_allowance` | Legacy numeric AUTO_CLOSE path; indexed single-event allowance, governing-authority gate still required | 0 AUTO_CLOSE |

`HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED` is a recommendation/review category, **not a final product fate**. It requires human review/signature, creates `PENDING_EVIDENCE`, cannot transition to CLOSED_AUTO (including via RECOMMENDED), and cannot itself be signed as a final disposition. Classification confidence is 0, not the former unjustified closure confidence. Temperature/storage/cumulative gates retain precedence.

Facts retain the original event `triage_outcome`; engine/API/bundles additionally expose `historical_classification`, `closure_eligibility`, `independent_closure_evidence` and `requires_human_review`. `evidence.closure_assessment` identifies the historical source, while `evidence.decision` and the trace preserve limitation labels. No caller-provided `*_verified` flag is trusted.

Every surface reports `verified_auto_close`, `historical_candidates_unverified`, and `other_auto_close_unverified` separately: **0/130/0**. AUTO_CLOSE alone is not verification. No current input/adapter produces independently verified eligibility; legacy nonhistorical numeric paths remain unvalidated prototypes. The 290 QA rows are unchanged, including 90 other historical closure-reference rows stopped by stronger evidence/authority gates.

Existing non-cumulative thresholds remain prototype heuristics. Once-only history, verified extra-constraint compliance, raw-series integrity and authoritative mappings are still missing. TT-CB-114 remains endpoint/common-offset sensitivity analysis on supplied summaries, not a calibrated correction or full raw-series proof. See [validation](validation/historical-candidates-review/report.md).

New one-sided instructions require an explicit Celsius unit; “Below 25” without a unit stays unresolved. Existing explicit unitless two-sided workbook shorthands retain their field-specific Celsius convention, not a general cross-document unit inference. A comma pair is recognised only in the explicit FROZEN tuple form, not ambiguous decimal-comma text.
