# AUTO_CLOSE path inventory (0.4.2)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Code inspection found seven emitting paths in `src/kestrel/decision_rules.py`. Executed adjudication of all 420 sample rows produced 130 AUTO_CLOSEs; every one is unverified historical classification. `autoclose-inventory.json` lists each event, actual deciding rule and stored limitation label. `evidence.decision` and the rationale trace carry these labels. The labels alone do not change a recommendation.

| Coded path | Sample count | Limitation |
|---|---:|---|
| `rule_facility_equipment_event` | 37 | Unverified historical classification: facility/no product loaded; not independent load verification |
| `rule_duplicate_alert` | 93 | Unverified historical classification: duplicate; not independent duplicate verification |
| `rule_gateway_gap` | 0 | Provided gap/interpolation flags and summaries; heuristic, not independent raw-series verification |
| `rule_sensor_artefact` | 0 | Unverified historical classification: sensor artefact; not independent sensor verification; near-limit heuristic |
| `rule_dock_door` | 0 | Unverified historical classification: dock door; not independent load/exposure verification; flag/duration heuristic |
| `rule_within_label_range` | 0 | Parsed temperature limits checked against supplied summaries only; other storage constraints and raw-series completeness not independently verified |
| `rule_stability_allowance` | 0 | Indexed single-event allowance candidate, not universal safety; governing authority gate still required |

The first measurement/storage guards and cumulative-history guard run before historical triage. Unknown instructions still route to QA, even with duplicate/facility text. For complete established bounds, historical triage outcomes remain unchanged solely by adding a limitation label.

`engine.adjudicate` marks AUTO_CLOSE as not requiring a human signature; this is existing prototype behaviour, not proof of safety. `CaseLifecycle.create` persists TRIAGED_NON_ACTIONABLE, not a final product-release state. Final product recommendations/manual signing have separate unresolved authority/authentication limitations. The five zero-count paths exist in code; their absence in this sample is not evidence they can never emit a closure.
