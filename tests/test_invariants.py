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

    def test_regulatory_deadline_after_alert_when_reportable(self) -> None:
        """Reportable events get a reg deadline on/after alert_ts."""
        for ev in self.svc.pack.events:  # type: ignore[union-attr]
            if str(ev.get("regulator_reportable") or "").upper() != "Y":
                continue
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            self.assertIsNotNone(r.reg_window_hours)
            self.assertIsNotNone(r.reg_deadline_utc)
            self.assertIsNotNone(ev.get("_alert_ts"))
            self.assertGreaterEqual(r.reg_deadline_utc, ev["_alert_ts"].isoformat(sep=" ")[:19])

    def test_bulletin_correction_monotonic(self) -> None:
        """All TT-2.14.3 events apply +1.8 °C corrected max."""
        for ev in self.svc.pack.events:  # type: ignore[union-attr]
            if str(ev.get("logger_fw")) != "TT-2.14.3":
                continue
            r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
            self.assertTrue(r.bulletin_applied)
            if ev.get("max_temp_c") is not None:
                self.assertEqual(r.corrected_max_temp_c, float(ev["max_temp_c"]) + 1.8)

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
