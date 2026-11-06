# Decision rules

`src/kestrel/decision_rules.py` holds every disposition rule as a small named function. `decide(facts)` runs them
in the order below and stops at the first one that returns a verdict. Rules that only add a note (for example the
SOP overlap) return nothing and let the chain continue. Every rule appends a plain-English line to the trace, so
the reviewer sees exactly why.

## Order

| # | Rule | Why it exists | Typical outcome |
|---|---|---|---|
| 1 | `rule_facility_equipment_event` | INC-2502 BMS storms: facility alarms with no product loaded | `AUTO_CLOSE` |
| 2 | `rule_duplicate_alert` | A duplicate adds no new evidence | `AUTO_CLOSE` |
| 3 | `rule_gateway_gap` | Interpolated readings across a long gateway gap are not evidence | `AUTO_CLOSE` / `RELEASE_WITH_NOTE` |
| 4 | `rule_unresolved_identity` | Unsure which product it is, so its stability data can't be applied | `ESCALATED_TO_SENIOR_QA` |
| 5 | `rule_presentation_mismatch` | Study may be for another presentation (vial vs pen) | `ESCALATED_TO_SENIOR_QA` |
| 6 | `rule_sop_overlap` | Two SOP revisions in force on one date: flag only (EXC-107133) | note |
| 7 | `rule_allowance_refer_qa` | The study itself says "Refer QA" | `ESCALATED_TO_SENIOR_QA` |
| 8 | `rule_unreadable_stability` | A cited study we can't read means a lab test, not a guess | `QUARANTINE_PENDING_LAB` |
| 9 | `rule_sensor_artefact` | No gap and peak close to the label | `AUTO_CLOSE` |
| 10 | `rule_dock_door` | Short dock-door ambient exposure | `AUTO_CLOSE` |
| 11 | `rule_within_label_range` | After the +1.8 °C correction, still inside the label | `AUTO_CLOSE` |
| 12 | `rule_freeze_damage` | Below 0 °C on a 2–8 °C product | `DESTROY` |
| 13 | `rule_ultra_cold` | Very short open on ultra-cold is a dry-ice top-up | `RELEASE_WITH_NOTE` / `DESTROY` |
| 14 | `rule_no_excursion_permitted` | Product allows no excursion | `QUARANTINE_PENDING_LAB` / `DESTROY` |
| 15 | `rule_stability_allowance` | Compare duration and peak with the allowance | `AUTO_CLOSE` / `RELEASE_WITH_NOTE` / lab / `DESTROY` |
| – | `rule_no_parseable_allowance` | Fallback: out of range, no usable allowance | `RELEASE_WITH_NOTE` (brief, mild) or `QUARANTINE_PENDING_LAB` |

Order matters. Identity and data-quality checks come before any temperature judgement, because a confident
temperature answer about the wrong product is worse than an escalation.

## Named thresholds

All magic numbers live at the top of the module with a name and a comment.

| Constant | Value | Meaning |
|---|---|---|
| `MIN_PRODUCT_CONFIDENCE` | 0.5 | Below this, identity is treated as unresolved |
| `GAP_MIN_MINUTES` | 30 | A gateway gap this long, with interpolation, is suspect |
| `GAP_SHARE_OF_EXCURSION` | 0.5 | ...or a gap covering half the excursion |
| `SENSOR_ARTEFACT_TOLERANCE_C` | 0.5 | Peak within this of the label counts as artefact |
| `DOCK_DOOR_MAX_MINUTES` | 20 | Longest exposure treated as a dock-door open |
| `DOCK_DOOR_TOLERANCE_C` | 5 | Max °C above label for a dock-door close |
| `COLD_CHAIN_MAX_LABEL_C` | 8 | Upper label of a 2–8 °C product |
| `ULTRA_COLD_TOP_UP_MINUTES` | 5 | Longest open treated as a dry-ice top-up |
| `BRIEF_BREACH_HOURS` | 0.25 | "Very brief" for no-excursion products |
| `BRIEF_BREACH_TOLERANCE_C` | 2 | "Mild" for no-excursion products |
| `CUMULATIVE_ABSOLUTE_CEILING_C` | 30 | Hard ceiling for cumulative allowances |
| `SEVERE_BREACH_MARGIN_C` | 5 | Beyond allowance by more than this means destroy |
| `MILD_EXCURSION_HOURS` | 0.5 | Fallback: short excursion |
| `MILD_EXCURSION_TOLERANCE_C` | 3 | Fallback: small excursion |
| `REPEAT_LANE_EXCURSIONS` | 3 | Prior excursions on a lane in 90 days that make it a pattern |

## Adding or changing a rule

1. Write the rule as `rule_<name>(facts: ExcursionFacts, trace: list[str]) -> Verdict | None` with a one-line
   docstring saying *why*.
2. Insert it into `DECISION_RULES` at the right position.
3. Add boundary tests to `tests/test_decision_rules.py` (one value on each side of the threshold).
4. Replay on the full pack and review every changed outcome before release.
   This is Dr Rao's gate: no rule change ships without a before/after diff.
