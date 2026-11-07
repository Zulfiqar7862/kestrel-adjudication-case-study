"""Agreement metrics and the 3am health report."""

from __future__ import annotations

from tests._base import _KestrelTestCase


class TestAgreementAndHealth(_KestrelTestCase):
    """Tests for agreement stratification and health/monitor signals."""

    def test_agreement_report_headline(self) -> None:
        """Agreement command math: 5.5% of 200 finals, 48.33% assistant on the stratified sample."""
        report = self.svc.agreement_report()
        self.assertEqual(report["events_total"], 420)
        self.assertEqual(report["events_with_historical_final"], 200)
        self.assertEqual(report["agree_with_historical_final"], 11)
        self.assertEqual(report["agree_with_historical_final_pct"], 5.5)
        self.assertEqual(report["agree_with_assistant"], 203)
        self.assertAlmostEqual(report["agree_with_assistant_pct"], 48.33, places=2)
        self.assertIn("EXC-107133", report["agree_event_ids"])
        self.assertTrue(report["disagree_by_reason"])
        self.assertTrue(report["disagree_by_tenant"])
        self.assertTrue(report["disagree_by_firmware"])

    def test_health_report_has_alert_catalog(self) -> None:
        """Health report exposes required alert names with thresholds and runbook steps."""
        # Persist a small slice so chain verify has length for at least one tenant
        self.svc.adjudicate_event("EXC-107133", persist=True)
        report = self.svc.health_report()
        names = {a["name"] for a in report["alerts"]}
        required = {
            "regulatory_deadline_breached",
            "regulatory_deadline_at_risk",
            "evidence_chain_verification_failure",
            "decision_mix_drift",
            "data_feed_staleness",
            "queue_age",
            "firmware_bulletin_change",
        }
        self.assertTrue(required.issubset(names))
        for alert in report["alerts"]:
            self.assertIn("threshold", alert)
            self.assertIn("page", alert)
            self.assertIn("runbook_step", alert)
        self.assertEqual(report["decision_mix"].get("AUTO_CLOSE"), 224)
        self.assertEqual(report["deadline_breached_in_pack"], 14)
        chain = report["chain_verification"].get("T-KAVERI") or {}
        self.assertTrue(chain.get("ok"))
