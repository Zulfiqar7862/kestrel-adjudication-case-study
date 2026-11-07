"""Independent durable notification lane; no evidence-engine or case-state join."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from kestrel.rules.regulatory import regulatory_clock
from kestrel.storage.bitemporal import BitemporalStore
from kestrel.utils import parse_datetime


class NotificationObligations:
    """Pending/uncertain filing work cannot be cleared by a product disposition.

    Filing references are not authenticated receipts. Without a validated filing
    adapter this implementation deliberately has no terminal FILED transition.
    """

    def __init__(self, store: BitemporalStore):
        self.store = store
        with store.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notification_obligation (tenant_code TEXT NOT NULL, event_id TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(tenant_code,event_id))"
            )
        self.sync_alerts()

    def sync_alerts(self):
        """Read already-ingested raw alerts, before any evidence assembly. Idempotent."""
        for event in self.store.list_alerts():
            tenant, event_id = event.get("tenant_code"), event.get("event_id")
            if not tenant or not event_id:
                continue
            clock = regulatory_clock(
                tenant,
                parse_datetime(event.get("alert_ts_utc")),
                historically_reportable=event.get("regulator_reportable"),
                historical_window_hours=event.get("reg_window_hours"),
            )
            row = {
                "tenant_code": tenant,
                "event_id": event_id,
                "state": "PENDING" if clock.reportable else "UNRESOLVED",
                "reportability_status": clock.reportability_status,
                "reportability_basis": "historical reference; requires applicability confirmation",
                "alert_ts_utc": event.get("alert_ts_utc"),
                "deadline_utc": None,
                "deadline_status": clock.deadline_status,
                "calendar_issue": clock.basis,
                "historical_window_reference": event.get("reg_window_hours"),
                "source_hash": hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest(),
                "filing_references": [],
            }
            with self.store.connection() as conn:
                # Re-ingestion cannot reset a pending obligation or its original clock.
                conn.execute(
                    "INSERT OR IGNORE INTO notification_obligation VALUES (?,?,?)",
                    (tenant, event_id, json.dumps(row, default=str)),
                )

    def queue(self, tenant_code: str):
        """All pending and uncertain obligations for exactly one named tenant."""
        if not tenant_code or not tenant_code.strip():
            raise ValueError("tenant scope required")
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM notification_obligation WHERE tenant_code=? ORDER BY event_id", (tenant_code,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def record_filing_reference(self, tenant_code: str, event_id: str, reference: str):
        """Record an unverified reference, not a filing and not clearance."""
        if not reference.strip():
            raise ValueError("nonempty filing reference required")
        with self.store.connection() as conn:
            found = conn.execute(
                "SELECT payload_json FROM notification_obligation WHERE tenant_code=? AND event_id=?",
                (tenant_code, event_id),
            ).fetchone()
            if not found:
                raise KeyError((tenant_code, event_id))
            row = json.loads(found[0])
            row["filing_references"].append({"reference": reference, "status": "UNVERIFIED"})
            conn.execute(
                "UPDATE notification_obligation SET payload_json=? WHERE tenant_code=? AND event_id=?",
                (json.dumps(row), tenant_code, event_id),
            )

    def counts(self):
        """Operational diagnostics, not proof of reportability or filing."""
        with self.store.connection() as conn:
            rows = conn.execute("SELECT payload_json FROM notification_obligation").fetchall()
        return dict(Counter(json.loads(r[0])["state"] for r in rows))
