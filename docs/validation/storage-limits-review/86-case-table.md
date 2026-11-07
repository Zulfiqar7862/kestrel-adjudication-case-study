# All 86 previously label-bound cases (0.4.2)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

All 86 were QA at 541202b. Raw text is the actual storage text chosen by the engine (tenant product master, otherwise received specification). Parsed text is not independent verification of the product mapping or source instructions. Extra constraints and complete rationales are preserved in `86-after.json`.

83 now have explicit parsed bounds; 3 remain unresolved. 27 now AUTO_CLOSE **on unverified historical classification**, not independent duplicate/load verification; 59 remain QA. Of those 59, only 3 are still unresolved storage instructions; the others are blocked by identity/study/SOP/uncertainty rules, as shown below.

| Event ID | Raw storage text | Parsed limit or unresolved reason | New outcome | Deciding rule |
|---|---|---|---|---|
| EXC-111008 | Controlled room temperature | UNRESOLVED: explicit governing temperature bounds not established from storage text | ESCALATED_TO_SENIOR_QA | rule_unresolved_storage |
| EXC-112352 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-111274 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111995 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-110854 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-112765 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112828 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111631 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112359 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110861 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-112506 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112772 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110735 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112835 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110434 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | temperature_uncertainty_gate |
| EXC-112436 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110280 | Store below 25 C | upper_only: <25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110672 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112226 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112681 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112499 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-111771 | Store below 25 C | upper_only: <25°C | ESCALATED_TO_SENIOR_QA | rule_presentation_mismatch |
| EXC-110112 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110616 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112296 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-110350 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-110910 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111407 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110819 | Store below 25 C | upper_only: <25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110623 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-112058 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110749 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110980 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-111939 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110035 | Controlled room temperature | UNRESOLVED: explicit governing temperature bounds not established from storage text | ESCALATED_TO_SENIOR_QA | rule_unresolved_storage |
| EXC-110539 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110133 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111561 | Store below 25 C | upper_only: <25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110077 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112457 | FROZEN (-25,-15) | two_sided: ≥-25°C, ≤-15°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111806 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111708 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-111757 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111659 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111491 | Store below 25 C | upper_only: <25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-111351 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112149 | Controlled room temperature | UNRESOLVED: explicit governing temperature bounds not established from storage text | ESCALATED_TO_SENIOR_QA | rule_unresolved_storage |
| EXC-111050 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111022 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111820 | Store below 25 C | upper_only: <25°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-111085 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112639 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110938 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110231 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111743 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-110777 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112464 | Store below 25 C | upper_only: <25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110161 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110441 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111967 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112625 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-110028 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111442 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111155 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-111134 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-110987 | Store below 25 C | upper_only: <25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-111904 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112310 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112478 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112926 | Store below 25 C | upper_only: <25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110322 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112184 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-110504 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-112107 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110259 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110462 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112072 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-111981 | 2°C – 8°C | two_sided: ≥2°C, ≤8°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110714 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-112023 | Store below 25 C | upper_only: <25°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-111484 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | ESCALATED_TO_SENIOR_QA | rule_release_authority_gate |
| EXC-110826 | -80C to -60C (dry ice permitted) | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112562 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_duplicate_alert |
| EXC-112541 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
| EXC-110833 | -80 to -60 °C | two_sided: ≥-80°C, ≤-60°C | AUTO_CLOSE | rule_facility_equipment_event |
| EXC-110805 | 15°C to 25°C (excursions to 30°C permitted, see stability) | two_sided: ≥15°C, ≤25°C | ESCALATED_TO_SENIOR_QA | rule_stability_authority |
