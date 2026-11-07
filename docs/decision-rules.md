# Decision rules (0.4.1)

Fixed rules produce prototype recommendations, not clinically validated product dispositions. `src/kestrel/decision_rules.py::decide` records a trace. The following ordered chain is followed by a conservative fallback and a final release-authority gate.

| Order | Function | Check |
|---|---|---|
| 1 | `rule_insufficient_temperature` | Historical triage is not independent proof of a duplicate or an empty load. |
| 2 | `rule_cumulative_history_unresolved` | No verified batch identity/history exists in this pack; never assume zero. |
| 3 | `rule_facility_equipment_event` | INC-2502 BMS storms: facility alarms with no product loaded close automatically. |
| 4 | `rule_duplicate_alert` | A duplicate of an earlier alert adds no new evidence. |
| 5 | `rule_gateway_gap` | Interpolated readings across a long gateway gap are not evidence of an excursion. |
| 6 | `rule_unresolved_identity` | If we are not sure which product it is, we cannot apply its stability data. |
| 7 | `rule_stability_authority` | An excursion with unestablished study applicability needs QA, not a guessed fate. |
| 8 | `rule_presentation_mismatch` | Never substitute unverified master prose for a mismatched study. |
| 9 | `rule_sop_overlap` | Record overlap; the final authority gate blocks release on any rule path. |
| 10 | `rule_allowance_refer_qa` | The study itself says 'Refer QA', so a person has to decide. |
| 11 | `rule_unreadable_stability` | A cited study we cannot read means a lab test, not a guess. |
| 12 | `rule_sensor_artefact` | Close a sensor artefact only when there is no gap and the peak is near the label. |
| 13 | `rule_dock_door` | Short dock-door ambient exposure; closes only if triage also says dock door. |
| 14 | `rule_within_label_range` | After the firmware correction, still inside the labelled range: nothing happened. |
| 15 | `rule_freeze_damage` | Below 0 °C on a 2–8 °C product risks freeze damage and is never released. |
| 16 | `rule_ultra_cold` | Ultra-cold / LN2: a very short open is likely a dry-ice top-up; a long one is a breach. |
| 17 | `rule_qualified_temperature_cap` | A cap is not permission below it; absent duration needs evidence/QA. |
| 18 | `rule_no_excursion_permitted` | The product allows no excursion: a very brief, mild breach goes to the lab, otherwise destroy. |
| 19 | `rule_stability_allowance` | Compare the excursion with the permitted allowance (duration and temperature). |

## Guards that cannot be skipped

- `rule_insufficient_temperature` runs first. Complete finite, ordered min/max and labelled bounds are required; incomplete/unknown is not false/no excursion. `is_out_of_range` returns `None` for unknown, otherwise True/False. Mean is optional for this extrema-based check. Historical duplicate/no-product labels are not independent proof, so there are **no exceptions** for missing extrema/label bounds.
- `rule_cumulative_history_unresolved` precedes historical triage. When an excursion requires a cumulative allowance, no verified batch identity/complete lifetime history exists: explicitly unresolved → QA. No ledger is invented, and unverified event fields cannot assert zero previous exposure. Proven in-range closure requires no cumulative arithmetic.
- `rule_stability_authority` escalates excursions whose cited study applicability is not established. `StabilityResolver.resolve` requires a unique tenant citation, product/presentation alignment, excursion study type, fully readable allowance, and never falls back to master text. It does not guess an alternate uncited study.
- The final gate catches RELEASE/RELEASE_WITH_NOTE from **all** paths and allowance-based AUTO_CLOSE. SOP absence, unresolved indexed site/body/annexure authority, overlap, or unresolved study authority forces QA. The workbook supplies no governing document contents, so engine release is not authorised from those pointers.

Noise/in-range AUTO_CLOSEs with complete extrema and label bounds remain prototype triage proposals; historical noise text still lacks live independent deduplication/no-product evidence. Manual signing is not an enforced authority-validation workflow.

## Remaining arithmetic and firmware limits

Existing non-cumulative thresholds remain heuristic, not new clinical rules. Cumulative lifetime arithmetic has been removed rather than pretending the full allowance remains. A once-only allowance still lacks a verified previous-use ledger.

TT-CB-114 compares reported and upper-bound summary scenarios without overwriting measurements. Up to 1.8°C is an uncertainty interval, not a calibrated correction; endpoints/common offset are not raw-series proof.

See [the report](validation/correctness-review/report.md) for actual sample counts, changed tests, test-first logs and limitations. No historical decision is treated as ground truth.
