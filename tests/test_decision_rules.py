"""Unit tests for each disposition rule, including boundary values.

These run without the data pack: every test builds the facts it needs directly.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from kestrel.decision_rules import (
    AUTO_CLOSE,
    DECISION_RULES,
    DESTROY,
    ESCALATE,
    HISTORICAL_CANDIDATE,
    QUARANTINE_PENDING_LAB,
    RELEASE_WITH_NOTE,
    ExcursionFacts,
    decide,
    is_out_of_range,
)
from kestrel.rules.identity import ResolvedProduct
from kestrel.rules.stability import StabilityPosition


def make_facts(**overrides) -> ExcursionFacts:
    """A resolved 2–8 °C product with no allowance, peaking at 10 °C for 60 minutes."""
    base = ExcursionFacts(
        event={},
        product=ResolvedProduct(tenant_code="T-TEST", match_method="gtin_exact", confidence=0.95),
        stability=StabilityPosition(study_ref=None, permitted_text=None, readable=True, source="product_master"),
        label_low_c=2.0,
        label_high_c=8.0,
        corrected_max_c=10.0,
        min_c=5.0,
        duration_min=60.0,
        sop_overlap=False,
        sop_authority_issue=None,  # Isolate temperature rules; engine tests cover unavailable SOP authority.
    )
    return replace(base, **overrides)


def stability(**fields) -> StabilityPosition:
    return StabilityPosition(study_ref="STB-1", permitted_text="text", readable=True, source="product_master", **fields)


class TestRuleOrder(unittest.TestCase):
    def test_rule_chain_is_ordered_and_named(self) -> None:
        names = [rule.__name__ for rule in DECISION_RULES]
        self.assertEqual(names[0], "rule_insufficient_temperature")
        self.assertLess(names.index("rule_unresolved_identity"), names.index("rule_within_label_range"))
        self.assertLess(names.index("rule_freeze_damage"), names.index("rule_stability_allowance"))

    def test_first_verdict_wins(self) -> None:
        unresolved = ResolvedProduct(tenant_code="T", match_method="none", confidence=0.0)
        facts = make_facts(event={"triage_outcome": "Duplicate"}, product=unresolved)
        verdict, _ = decide(facts)
        self.assertEqual(verdict.disposition, HISTORICAL_CANDIDATE)


class TestNonActionable(unittest.TestCase):
    def test_facility_equipment_event_requires_review(self) -> None:
        verdict, trace = decide(make_facts(event={"triage_outcome": "Facility equipment event"}))
        self.assertEqual(verdict.disposition, HISTORICAL_CANDIDATE)
        self.assertIn("not independent load verification", trace[0])

    def test_gateway_gap_boundary_at_30_minutes(self) -> None:
        at_limit = make_facts(event={"gateway_gap_min": 30, "interpolated": "Y"}, duration_min=10)
        below = make_facts(event={"gateway_gap_min": 29, "interpolated": "Y"}, duration_min=10)
        self.assertEqual(decide(at_limit)[0].triage_label, "NON_ACTIONABLE — sensor artefact (gap)")
        self.assertNotEqual(decide(below)[0].triage_label, "NON_ACTIONABLE — sensor artefact (gap)")

    def test_within_label_range_after_correction(self) -> None:
        self.assertEqual(decide(make_facts(corrected_max_c=8.0))[0].disposition, AUTO_CLOSE)
        self.assertNotEqual(decide(make_facts(corrected_max_c=8.01))[0].disposition, AUTO_CLOSE)


class TestEscalations(unittest.TestCase):
    def test_low_product_confidence_escalates(self) -> None:
        unsure = ResolvedProduct(tenant_code="T", match_method="fuzzy", confidence=0.49)
        sure = ResolvedProduct(tenant_code="T", match_method="fuzzy", confidence=0.5)
        self.assertEqual(decide(make_facts(product=unsure))[0].disposition, ESCALATE)
        self.assertNotEqual(decide(make_facts(product=sure))[0].disposition, ESCALATE)

    def test_presentation_mismatch_escalates_even_with_master_allowance(self) -> None:
        risky = stability(presentation_mismatch_risk=True)
        self.assertEqual(decide(make_facts(stability=risky))[0].disposition, ESCALATE)
        fallback = replace(risky, source="product_master_over_mismatched_study")
        self.assertEqual(decide(make_facts(stability=fallback))[0].disposition, ESCALATE)

    def test_refer_qa_escalates(self) -> None:
        self.assertEqual(decide(make_facts(stability=stability(notes=["Refer QA"])))[0].disposition, ESCALATE)

    def test_unreadable_study_goes_to_lab(self) -> None:
        unreadable = StabilityPosition(study_ref="STB-9", permitted_text=None, readable=False, source="none")
        self.assertEqual(decide(make_facts(stability=unreadable))[0].disposition, QUARANTINE_PENDING_LAB)

    def test_sop_overlap_is_flagged(self) -> None:
        _, trace = decide(make_facts(sop_overlap=True))
        self.assertTrue(any("SOP revision overlap" in line for line in trace))


class TestTemperatureRules(unittest.TestCase):
    def test_freeze_on_2_8_product_destroys(self) -> None:
        self.assertEqual(decide(make_facts(min_c=-0.1, corrected_max_c=6.0))[0].disposition, DESTROY)

    def test_ultra_cold_short_open_is_release_with_note(self) -> None:
        facts = make_facts(label_low_c=-80, label_high_c=-60, corrected_max_c=-40, min_c=-80, duration_min=5)
        self.assertEqual(decide(facts)[0].disposition, RELEASE_WITH_NOTE)

    def test_no_excursion_product(self) -> None:
        brief = make_facts(stability=stability(no_excursion=True), duration_min=15, corrected_max_c=10.0)
        longer = replace(brief, duration_min=16)
        self.assertEqual(decide(brief)[0].disposition, QUARANTINE_PENDING_LAB)
        self.assertEqual(decide(longer)[0].disposition, DESTROY)

    def test_cumulative_allowance_without_batch_history_escalates(self) -> None:
        cumulative = stability(max_duration_hours=72, cumulative_above_label=True)
        verdict, _ = decide(make_facts(stability=cumulative, corrected_max_c=11.2, duration_min=15))
        self.assertEqual(verdict.disposition, ESCALATE)
        self.assertEqual(verdict.confidence, 0.0)

    def test_allowance_exceeded_by_more_than_5c_destroys(self) -> None:
        capped = stability(max_duration_hours=2, max_temp_c=25)
        self.assertEqual(decide(make_facts(stability=capped, corrected_max_c=30.1))[0].disposition, DESTROY)
        self.assertEqual(
            decide(make_facts(stability=capped, corrected_max_c=30.0))[0].disposition, QUARANTINE_PENDING_LAB
        )

    def test_fallback_repeat_lane_goes_to_lab(self) -> None:
        verdict, trace = decide(make_facts(event={"prior_excursions_lane_90d": 3}, corrected_max_c=15))
        self.assertEqual(verdict.triage_label, "ACTIONABLE — repeat lane pattern")
        self.assertTrue(any("prior excursions" in line for line in trace))


class TestOutOfRange(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertFalse(is_out_of_range(8.0, 2.0, 2.0, 8.0))
        self.assertTrue(is_out_of_range(8.1, 2.0, 2.0, 8.0))
        self.assertTrue(is_out_of_range(7.0, 1.9, 2.0, 8.0))
        self.assertIsNone(is_out_of_range(None, None, 2.0, 8.0))


if __name__ == "__main__":
    unittest.main()
