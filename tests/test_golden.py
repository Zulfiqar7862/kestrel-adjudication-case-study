"""Golden cases: the brief's EXC-107133 and engine edge cases."""

from __future__ import annotations

from kestrel.engine import DESTROY, ESCALATE, QUARANTINE_PENDING_LAB
from tests._base import _KestrelTestCase


class TestGoldenExc107133(_KestrelTestCase):
    """Golden tests for hero case EXC-107133 (QA escalation)."""

    def test_exc_107133_escalates_unresolved_authority(self) -> None:
        """Persist EXC-107133 and assert QA escalation plus GTIN evidence."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        self.assertEqual(out["result"].recommendation, ESCALATE)
        self.assertTrue(out["bundle"]["bundle_id"].startswith("EVB-"))
        self.assertEqual(out["bundle"]["inputs"]["resolution"]["product"]["gtin"], "08901234500035")

    def test_exc_107133_brief_narrative(self) -> None:
        """Assert brief narrative fields: signature required, no bulletin, 11.2 °C."""
        ev = self.svc.pack.event_by_id("EXC-107133")  # type: ignore[union-attr]
        assert ev is not None
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertEqual(r.recommendation, ESCALATE)
        self.assertTrue(r.requires_human_signature)
        self.assertFalse(r.bulletin_applied)
        self.assertEqual(r.reported_max_temp_c, 11.2)
        self.assertIsNotNone(r.evidence.get("product"))
        self.assertTrue(r.reg_deadline_utc or r.reg_window_hours)


class TestEngineGolden(_KestrelTestCase):
    """Engine golden / narrative cases beyond EXC-107133."""

    def test_exc_110448_bulletin_underread(self) -> None:
        """TT-2.14.3 is flagged for bounded analysis; reported maximum stays unchanged."""
        ev = self.svc.pack.event_by_id("EXC-110448")  # type: ignore[union-attr]
        if ev is None:
            self.skipTest("EXC-110448 not in pack")
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertTrue(r.bulletin_applied)
        self.assertIsNotNone(r.reported_max_temp_c)
        self.assertEqual(r.reported_max_temp_c, float(ev["max_temp_c"]))

    def test_override_freeze_vaccine_pattern(self) -> None:
        """Below-0 °C adjuvanted vaccine does not RELEASE_WITH_NOTE."""
        ev = self.svc.pack.event_by_id("EXC-110483")  # type: ignore[union-attr]
        if ev is None:
            self.skipTest("EXC-110483 not in pack")
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertIn(r.recommendation, {DESTROY, ESCALATE, QUARANTINE_PENDING_LAB})

    def test_facility_storm_insufficient_evidence_escalates(self) -> None:
        """Historical facility triage cannot bypass unresolved label/temperature evidence."""
        candidates = [
            e
            for e in self.svc.pack.events  # type: ignore[union-attr]
            if e.get("notes")
            and "Whitefield" in str(e.get("notes"))
            and "facility equipment" in str(e.get("triage_outcome") or "").lower()
        ]
        self.assertTrue(candidates, "expected INC-2502 facility rows")
        r = self.svc.engine.adjudicate(candidates[0])  # type: ignore[union-attr]
        self.assertEqual(r.recommendation, ESCALATE)
        self.assertIn("insufficient temperature evidence", " ".join(r.rationale))

    def test_every_event_produces_structured_result(self) -> None:
        """Every pack event yields a structured recommendation and evidence."""
        for ev in self.svc.pack.events:  # type: ignore[union-attr]
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            self.assertEqual(r.event_id, ev["event_id"])
            self.assertTrue(r.recommendation)
            self.assertGreaterEqual(r.confidence, 0.0)
            self.assertLessEqual(r.confidence, 1.0)
            self.assertIsInstance(r.rationale, list)
            self.assertIn("temps", r.evidence)
