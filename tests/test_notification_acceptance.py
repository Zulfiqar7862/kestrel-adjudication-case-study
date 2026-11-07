"""Item 2 acceptance criteria: independent persisted obligations and scoped access."""

from unittest.mock import patch

import pytest

from tests._base import _KestrelTestCase


class TestNotificationAcceptance(_KestrelTestCase):
    def pending(self):
        event = next(e for e in self.svc.pack.events if e.get("regulator_reportable") == "Y")
        return event["tenant_code"], event["event_id"]

    def test_criterion_1_signing_does_not_remove_outstanding_obligation(self):
        from kestrel.domain import Disposition

        tenant, event_id = self.pending()
        before = next(o for o in self.svc.notifications.queue(tenant) if o["event_id"] == event_id)
        result = self.svc.adjudicate_event(event_id)
        self.svc.lifecycle.sign(
            result["case"]["case_id"],
            "Fixture reviewer",
            Disposition.QUARANTINE_PENDING_LAB,
            bundle_hash=result["bundle"]["content_hash"],
        )
        after = next(o for o in self.svc.notifications.queue(tenant) if o["event_id"] == event_id)
        assert after == before
        assert after["state"] == "PENDING"

    def test_criterion_2_assembly_failure_does_not_stop_deadline_tracking(self):
        tenant, _ = self.pending()
        before = self.svc.notifications.queue(tenant)
        with patch.object(self.svc.engine, "adjudicate", side_effect=RuntimeError("assembly unavailable")):
            with pytest.raises(RuntimeError, match="assembly unavailable"):
                self.svc.adjudicate_event("EXC-107133")
            assert self.svc.notifications.queue(tenant) == before
        with patch.object(self.svc, "bootstrap", side_effect=RuntimeError("reference source unavailable")):
            from kestrel.notifications import NotificationObligations
            from kestrel.storage.bitemporal import BitemporalStore

            lane = NotificationObligations(BitemporalStore(self.svc.settings.db_path))
            assert lane.queue(tenant) == before
        assert all(o["alert_ts_utc"] and o["deadline_status"] == "UNKNOWN" for o in before)

    def test_criterion_3_restart_keeps_sqlite_obligations(self):
        from kestrel.notifications import NotificationObligations
        from kestrel.storage.bitemporal import BitemporalStore

        tenant, event_id = self.pending()
        before = self.svc.notifications.queue(tenant)
        reopened = NotificationObligations(BitemporalStore(self.svc.settings.db_path))
        assert reopened.queue(tenant) == before
        assert next(o for o in reopened.queue(tenant) if o["event_id"] == event_id)["state"] == "PENDING"
        # Fresh OS process, with the workbook deliberately unavailable: no
        # in-memory service/case/assembler state can make this test pass.
        import json
        import subprocess
        import sys

        raw = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "kestrel",
                "--log-level",
                "WARNING",
                "--db",
                str(self.svc.settings.db_path),
                "--evidence-dir",
                str(self.svc.settings.evidence_dir),
                "--pack",
                "/tmp/notification-test-no-workbook.xlsx",
                "notifications",
                "--tenant",
                tenant,
            ],
            text=True,
        )
        assert json.loads(raw)["items"] == before

    def test_criterion_4_unknown_never_means_not_reportable(self):
        from datetime import datetime

        from kestrel.rules.regulatory import regulatory_clock

        for flag in (None, "", "N", "unknown"):
            clock = regulatory_clock("T", datetime(2026, 2, 13), historically_reportable=flag)
            assert clock.reportable is None
            assert clock.reportability_status == "UNKNOWN"
            assert clock.deadline_status == "UNKNOWN"
            assert clock.deadline_utc is None
        unknown = [o for o in self.svc.notifications.queue("T-KAVERI") if o["reportability_status"] == "UNKNOWN"]
        assert unknown and all(o["state"] == "UNKNOWN" for o in unknown)

    def test_criterion_5_delivery_retries_acknowledgement_are_not_dispositions(self):
        from kestrel.notifications import NotificationObligations, NotificationPrincipal
        from kestrel.storage.bitemporal import BitemporalStore

        tenant, event_id = self.pending()
        actor = NotificationPrincipal("fixture-operator", frozenset({tenant}), frozenset({tenant}))
        case_before = self.svc.lifecycle.storm_safe_queue()
        lane = self.svc.notifications
        failed = lane.record_delivery_attempt(
            actor, tenant, event_id, outcome="FAILED", reference="fixture failure", retry_at="2026-12-01T12:00:00Z"
        )
        row = next(o for o in lane.queue(tenant) if o["event_id"] == event_id)
        assert row["delivery_status"] == "RETRY_PENDING"
        assert row["retry_at"] == "2026-12-01T12:00:00Z"
        sent = lane.record_delivery_attempt(actor, tenant, event_id, outcome="SENT", reference="fixture sent")
        lane.record_delivery_acknowledgement(actor, tenant, event_id, sent["attempt_id"], "fixture receipt")
        restarted = NotificationObligations(BitemporalStore(self.svc.settings.db_path))
        row = next(o for o in restarted.queue(tenant) if o["event_id"] == event_id)
        assert row["state"] == "PENDING"
        assert row["delivery_status"] == "ACK_RECORDED_UNVERIFIED"
        assert [a["attempt_id"] for a in row["delivery_attempts"]] == [failed["attempt_id"], sent["attempt_id"]]
        assert row["acknowledgements"][0]["verification"] == "UNVERIFIED_REFERENCE"
        assert self.svc.lifecycle.storm_safe_queue() == case_before

    def test_criterion_6_tenant_authorisation_for_read_and_update(self):
        from fastapi.testclient import TestClient

        from kestrel.api.app import create_notification_app

        tenant, event_id = self.pending()
        client = TestClient(create_notification_app(self.svc.notifications))
        assert client.get("/notifications", params={"tenant_code": tenant}).status_code == 401
        from hashlib import sha256

        from kestrel.notifications import NotificationAccess, NotificationPrincipal

        writer = NotificationPrincipal("fixture-operator", frozenset({tenant}), frozenset({tenant}))
        reader = NotificationPrincipal("fixture-reader", frozenset({tenant}), frozenset())
        access = NotificationAccess(
            {sha256(b"fixture-write").hexdigest(): writer, sha256(b"fixture-read").hexdigest(): reader}
        )
        client = TestClient(create_notification_app(self.svc.notifications, notification_access=access))
        headers = {"Authorization": "Bearer fixture-write"}
        readonly = {"Authorization": "Bearer fixture-read"}
        assert client.get("/notifications", params={"tenant_code": tenant}, headers=headers).status_code == 200
        assert client.get("/notifications", params={"tenant_code": "FOREIGN"}, headers=headers).status_code == 403
        assert (
            client.get(
                "/notifications", params={"tenant_code": tenant}, headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        path = f"/notifications/{tenant}/{event_id}/attempts"
        payload = {"outcome": "FAILED", "reference": "fixture failure"}
        assert client.post(path, json=payload, headers=readonly).status_code == 403
        assert client.post(path.replace(tenant, "FOREIGN"), json=payload, headers=headers).status_code == 403
        posted = client.post(path, json=payload, headers=headers)
        assert posted.status_code == 200
        assert posted.json()["actor"] == "fixture-operator"
        assert client.post(path, json={**payload, "actor": "spoofed"}, headers=headers).status_code == 422
        sent = client.post(path, json={"outcome": "SENT", "reference": "fixture sent"}, headers=headers)
        receipt = {"attempt_id": sent.json()["attempt_id"], "reference": "fixture receipt"}
        ack_path = path.replace("/attempts", "/acknowledgements")
        assert client.post(ack_path, json=receipt).status_code == 401
        assert client.post(ack_path, json=receipt, headers=readonly).status_code == 403
        assert client.post(ack_path.replace(tenant, "FOREIGN"), json=receipt, headers=headers).status_code == 403
        assert client.post(ack_path, json=receipt, headers=headers).status_code == 200
        assert client.post(ack_path, json=receipt, headers=headers).status_code == 200
        bad_receipt = {"attempt_id": posted.json()["attempt_id"], "reference": "cannot acknowledge FAILED"}
        assert client.post(ack_path, json=bad_receipt, headers=headers).status_code == 422
        # In-process callers must also possess tenant/write grants.
        from kestrel.exceptions import TenantIsolationError

        with pytest.raises(TenantIsolationError):
            self.svc.notifications.record_delivery_attempt(reader, tenant, event_id, **payload)
        with pytest.raises(TenantIsolationError):
            self.svc.notifications.read_queue(writer, "FOREIGN")

    def test_notification_authorisation_is_identical_in_the_main_api(self):
        from hashlib import sha256

        from fastapi.testclient import TestClient

        from kestrel.api.app import create_app
        from kestrel.notifications import NotificationAccess, NotificationPrincipal

        tenant, _ = self.pending()
        access = NotificationAccess(
            {sha256(b"fixture").hexdigest(): NotificationPrincipal("fixture", frozenset({tenant}), frozenset())}
        )
        client = TestClient(create_app(self.svc, notification_access=access))
        assert client.get("/notifications", params={"tenant_code": tenant}).status_code == 401
        headers = {"Authorization": "Bearer fixture"}
        assert client.get("/notifications", params={"tenant_code": tenant}, headers=headers).status_code == 200
        assert client.get("/notifications", params={"tenant_code": "FOREIGN"}, headers=headers).status_code == 403
        assert "notification_obligations" not in client.get("/ops/health-report").json()
