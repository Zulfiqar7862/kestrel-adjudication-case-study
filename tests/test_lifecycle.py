"""Case lifecycle: sign, reopen, deadline-ordered queue."""

from __future__ import annotations

from kestrel.domain import CaseState, Disposition, TransitionError
from tests._base import _KestrelTestCase


class TestLifecycle(_KestrelTestCase):
    """Case lifecycle sign/reopen and regulatory-deadline queue ordering."""

    def test_lifecycle_sign_and_reopen_months_later(self) -> None:
        """Sign RELEASE_WITH_NOTE then reopen for bulletin; prior case marked REOPENED."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        case = out["case"]
        self.assertIn(
            case["state"],
            {
                CaseState.AWAITING_REVIEWER.value,
                CaseState.TRIAGED_NON_ACTIONABLE.value,
                CaseState.REOPENED.value,
            },
        )
        try:
            signed = self.svc.lifecycle.sign(case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE)
        except TransitionError:
            self.svc.lifecycle.transition(case["case_id"], CaseState.RECOMMENDED)
            self.svc.lifecycle.transition(case["case_id"], CaseState.AWAITING_REVIEWER)
            signed = self.svc.lifecycle.sign(case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE)
        self.assertEqual(signed["state"], CaseState.CLOSED_SIGNED.value)
        self.assertEqual(signed["signed_by"], "QA-IN-04")
        revision = self.svc.lifecycle.reopen(signed["case_id"], "BULLETIN_TT_CB_114")
        self.assertEqual(revision["reopened_from_case_id"], signed["case_id"])
        self.assertEqual(revision["state"], CaseState.REOPENED.value)
        prior = self.svc.store.get_case(signed["case_id"])
        self.assertEqual(prior["state"], CaseState.REOPENED.value)

    def test_queue_orders_by_reg_deadline(self) -> None:
        """Storm-safe queue sorts reportable cases by reg_deadline_utc ascending."""
        for eid in ["EXC-107133", "EXC-110637", "EXC-110651"]:
            if self.svc.pack.event_by_id(eid):  # type: ignore[union-attr]
                self.svc.adjudicate_event(eid, persist=True)
        q = self.svc.lifecycle.storm_safe_queue(limit=50)
        deadlines = [c.get("reg_deadline_utc") or "9999" for c in q if c.get("regulator_reportable")]
        self.assertEqual(deadlines, sorted(deadlines))
