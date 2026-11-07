# Decision rules (0.4.2)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Fixed rules produce prototype recommendations. `decision_rules.decide` records the actual deciding function and an explicit limitation for every AUTO_CLOSE.

## Ordered guards and authority

1. `rule_insufficient_temperature`: missing required max/min, nonfinite or reversed supplied extrema → QA. Required extrema depend on the explicit bound type; mean cannot substitute.
2. `rule_unresolved_storage`: absent, malformed or unclear governing storage bounds → QA, separately from measurement insufficiency.
3. `rule_cumulative_history_unresolved`: cumulative excursion with unavailable verified batch/history → QA, before historical triage. No zero-history assumption.
4. Existing triage and temperature/stability rules run in their prior order. `rule_stability_authority` rejects an excursion with unestablished cited-study applicability.
5. Final `rule_release_authority_gate` blocks release recommendations and allowance-based closures on unresolved study/SOP/site/annexure/overlap authority.

The numeric parser supports explicit inclusive pairs, strict/inclusive upper-only and lower-only bounds. “Below 25 C” does **not** imply a lower bound; “≤ −150 C” does **not** imply −196 C. Plain “controlled room temperature”, nominal cryogenic descriptions and unknown residual clauses remain unresolved. Extra restrictions are retained separately and marked not independently verified, not converted into invented numeric limits.

## Every coded AUTO_CLOSE path

| Function | Limitation (recorded in trace/evidence) | Current sample |
|---|---|---:|
| `rule_duplicate_alert` | **Unverified historical classification**, not independent duplicate verification | 93 |
| `rule_facility_equipment_event` | **Unverified historical classification**, not independent load/no-product verification | 37 |
| `rule_sensor_artefact` | **Unverified historical classification** plus near-limit heuristic; not independent sensor verification | 0 |
| `rule_dock_door` | **Unverified historical classification** plus provided flag/duration heuristic; not independent load/exposure verification | 0 |
| `rule_gateway_gap` | Provided gap/interpolation summaries; not independent raw-series verification | 0 |
| `rule_within_label_range` | Supplied summaries satisfy parsed bounds only; raw-series completeness/other constraints unverified | 0 |
| `rule_stability_allowance` | Indexed single-event allowance candidate; still subject to governing-authority gate | 0 |

Historical labels were **not** upgraded to verified facts or changed solely because of their provenance. Every one of the 130 sample AUTO_CLOSEs is historical classification, not independently demonstrated safety.

Existing non-cumulative thresholds remain prototype heuristics. Once-only history, verified extra-constraint compliance, raw-series integrity and authoritative mappings are still missing. TT-CB-114 remains endpoint/common-offset sensitivity analysis on supplied summaries, not a calibrated correction or full raw-series proof. See [validation](validation/storage-limits-review/report.md).

New one-sided instructions require an explicit Celsius unit; “Below 25” without a unit stays unresolved. Existing explicit unitless two-sided workbook shorthands retain their field-specific Celsius convention, not a general cross-document unit inference. A comma pair is recognised only in the explicit FROZEN tuple form, not ambiguous decimal-comma text.
