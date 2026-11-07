"""Invariants that must hold for every event in the pack."""

from __future__ import annotations

from datetime import datetime

from kestrel.engine import ACTIONABLE_DISPOSITIONS, AUTO_CLOSE
from tests._base import _KestrelTestCase


class TestInvariants(_KestrelTestCase):
    """Cross-pack invariants that must hold for every (or many) events."""

    def test_auto_close_never_requires_human(self) -> None:
        """AUTO_CLOSE never requires human signature; actionable always does."""
        for ev in self.svc.pack.events:  # type: ignore[union-attr]
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            if r.recommendation == AUTO_CLOSE:
                self.assertFalse(r.requires_human_signature)
            if r.recommendation in ACTIONABLE_DISPOSITIONS:
                self.assertTrue(r.requires_human_signature)

    def test_uncontrolled_regulatory_deadline_remains_unresolved_and_queued(self) -> None:
        """Historical reportability never licenses an invented legal deadline."""
        for ev in self.svc.pack.events:
            if str(ev.get("regulator_reportable") or "").upper() != "Y":
                continue
            r = self.svc.engine.adjudicate(ev)
            self.assertIsNone(r.reg_window_hours)
            self.assertIsNone(r.reg_deadline_utc)
            self.assertEqual(r.evidence["regulatory"]["deadline_status"], "UNKNOWN")
            pending = {o["event_id"]: o for o in self.svc.notifications.queue(ev["tenant_code"])}
            self.assertEqual(pending[ev["event_id"]]["reportability_status"], "REPORTABLE")
            self.assertEqual(pending[ev["event_id"]]["state"], "PENDING")

    def test_bulletin_preserves_reported_and_records_bound(self) -> None:
        """All TT-2.14.3 events keep measurements and record both endpoint scenarios."""
        for ev in self.svc.pack.events:  # type: ignore[union-attr]
            if str(ev.get("logger_fw")) != "TT-2.14.3":
                continue
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            self.assertTrue(r.bulletin_applied)
            if ev.get("max_temp_c") is not None:
                self.assertEqual(r.reported_max_temp_c, float(ev["max_temp_c"]))
                u = r.evidence["temps"]["uncertainty"]
                self.assertEqual(u["upper_bound_scenario"]["max_c"], float(ev["max_temp_c"]) + 1.8)

    def test_sop_as_of_never_returns_future_revision(self) -> None:
        """Selected SOP effective_from is never after the excursion date."""
        checked = 0
        for ev in self.svc.pack.events[:80]:  # type: ignore[union-attr]
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            if not r.sop_doc_id:
                continue
            as_of = (ev.get("_excursion_start") or ev.get("_alert_ts")).date()
            sop = r.evidence.get("sop") or {}
            ef = sop.get("effective_from")
            if ef and ef != "None":
                ef_d = datetime.strptime(ef, "%Y-%m-%d").date()
                self.assertLessEqual(ef_d, as_of)
                checked += 1
        self.assertGreater(checked, 0)
