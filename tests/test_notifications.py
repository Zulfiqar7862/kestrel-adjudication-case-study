"""Filing obligations do not belong to the disposition lifecycle."""

from datetime import date, datetime
from unittest.mock import patch

import pytest

from kestrel.rules.regulatory import regulatory_clock
from tests._base import _KestrelTestCase


def test_historical_us_window_is_not_a_controlled_business_calendar():
    clock = regulatory_clock(
        "T-PINNACLE", datetime(2026, 2, 13, 18), historically_reportable="Y", historical_window_hours=24
    )
    assert clock.deadline_utc is None
    assert clock.deadline_status == "UNRESOLVED"
    assert clock.reportability_status == "REPORTABLE"


@pytest.mark.parametrize("flag", [None, "", "N", "unknown"])
def test_absence_of_verified_applicability_does_not_prove_no_obligation(flag):
    clock = regulatory_clock("unknown", datetime(2026, 2, 13), historically_reportable=flag)
    assert clock.deadline_utc is None
    assert clock.reportability_status == "UNRESOLVED"


def test_controlled_business_calendar_is_explicit_scoped_and_bounded():
    from kestrel.rules.regulatory import NotificationRule

    rule = NotificationRule(
        rule_id="fixture-policy-v1",
        tenant_code="T",
        product_ref="P",
        market="M",
        kind="next_business_day",
        amount=1,
        timezone="America/New_York",
        cutoff="17:00",
        weekends=(5, 6),
        holidays=(date(2026, 2, 16),),
        calendar_start=date(2026, 1, 1),
        calendar_end=date(2026, 12, 31),
        source_hash="a" * 64,
        approval_ref="fixture approval, not a production rule",
    )
    args = dict(
        tenant_code="T",
        alert_ts=datetime(2026, 2, 13, 18),
        historically_reportable="Y",
        rule=rule,
        product_ref="P",
        market="M",
    )
    assert regulatory_clock(**args).deadline_utc == datetime(2026, 2, 17, 22)
    assert regulatory_clock(**{**args, "market": "foreign"}).deadline_utc is None
    assert regulatory_clock(**{**args, "alert_ts": datetime(2027, 1, 1)}).deadline_utc is None


class TestIndependentNotifications(_KestrelTestCase):
    def test_sign_reopen_failure_and_storm_never_hide_pending_reportable(self):
        from kestrel.domain import Disposition

        service = self.svc
        event = next(e for e in service.pack.events if str(e.get("regulator_reportable")).upper() == "Y")
        tenant, event_id = event["tenant_code"], event["event_id"]
        before = service.notifications.queue(tenant)
        pending = next(o for o in before if o["event_id"] == event_id)
        assert pending["reportability_status"] == "REPORTABLE"
        out = service.adjudicate_event(event_id)
        service.lifecycle.sign(
            out["case"]["case_id"],
            "Fixture Reviewer",
            Disposition.QUARANTINE_PENDING_LAB,
            bundle_hash=out["bundle"]["content_hash"],
        )
        service.lifecycle.reopen(out["case"]["case_id"], "new source")
        with patch.object(service.engine, "adjudicate", side_effect=RuntimeError("assembler down")):
            assert service.notifications.queue(tenant) == before
        # A reference receipt cannot certify a legal filing or extinguish a task.
        service.notifications.record_filing_reference(tenant, event_id, "unverified receipt")
        again = next(o for o in service.notifications.queue(tenant) if o["event_id"] == event_id)
        assert again["state"] == "PENDING"
        assert again["alert_ts_utc"] == pending["alert_ts_utc"]
        assert len(service.notifications.queue(tenant)) == len(before)

    def test_notification_http_service_does_not_bootstrap_engine_or_read_case_queue(self):
        from fastapi.testclient import TestClient

        from kestrel.api.app import create_notification_app

        with patch.object(self.svc, "bootstrap", side_effect=RuntimeError("source down")):
            with patch.object(self.svc.lifecycle, "storm_safe_queue", side_effect=RuntimeError("case queue down")):
                client = TestClient(create_notification_app(self.svc.notifications))
                response = client.get("/notifications", params={"tenant_code": "T-KAVERI"})
                assert response.status_code == 200
                assert response.json()["items"]
                assert all(o["tenant_code"] == "T-KAVERI" for o in response.json()["items"])
                assert client.get("/notifications").status_code == 422


def test_calendar_days_use_declared_local_cutoff_across_dst():
    from kestrel.rules.regulatory import NotificationRule

    rule = NotificationRule(
        "fixture",
        "T",
        "P",
        "M",
        "calendar_days",
        1,
        "a" * 64,
        "fixture approval",
        timezone="Europe/Berlin",
        cutoff="17:00",
        calendar_start=date(2026, 1, 1),
        calendar_end=date(2026, 12, 31),
    )
    assert rule.deadline(datetime(2026, 3, 28, 12)) == datetime(2026, 3, 29, 15)
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(rule, cutoff="02:30").deadline(datetime(2026, 3, 28, 12))
    with pytest.raises(ValueError):
        replace(rule, source_hash="").deadline(datetime(2026, 3, 28, 12))
