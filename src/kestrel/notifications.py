"""Independent durable notification lane; no evidence-engine or case-state join."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hmac import compare_digest
from typing import Mapping
from uuid import uuid4

from kestrel.exceptions import TenantIsolationError
from kestrel.rules.regulatory import regulatory_clock
from kestrel.storage.bitemporal import BitemporalStore
from kestrel.utils import parse_datetime, utc_now


@dataclass(frozen=True)
class NotificationPrincipal:
    """Trusted adapter grants, not tenant names supplied by an HTTP caller."""

    subject: str
    read_tenants: frozenset[str]
    write_tenants: frozenset[str]

    def __post_init__(self):
        if not self.subject.strip():
            raise ValueError("authenticated subject required")
        object.__setattr__(self, "read_tenants", frozenset(self.read_tenants))
        object.__setattr__(self, "write_tenants", frozenset(self.write_tenants))

    def authorize(self, tenant_code: str, *, write: bool = False):
        if tenant_code not in (self.write_tenants if write else self.read_tenants):
            raise TenantIsolationError("notification tenant/permission not granted")


class NotificationAccess:
    """Explicit credential-digest grants. Empty configuration fails closed.

    An embedding deployment supplies SHA-256 digests of high-entropy bearer
    credentials and approved grants. No tokens are generated, logged or shipped.
    This narrow adapter is not a production SSO/credential-lifecycle integration.
    """

    def __init__(self, grants: Mapping[str, NotificationPrincipal] | None = None):
        self._grants = dict(grants or {})
        if any(len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in self._grants):
            raise ValueError("credential grants require SHA-256 digests")

    def authenticate(self, authorization: str | None) -> NotificationPrincipal:
        parts = (authorization or "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 8192:
            raise PermissionError("notification authentication required")
        digest = hashlib.sha256(parts[1].encode()).hexdigest()
        for expected, principal in self._grants.items():
            if compare_digest(digest, expected):
                return principal
        raise PermissionError("invalid notification credential")


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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notification_delivery_event (sequence INTEGER PRIMARY KEY AUTOINCREMENT, tenant_code TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('ATTEMPT','ACK')), payload_json TEXT NOT NULL, FOREIGN KEY(tenant_code,event_id) REFERENCES notification_obligation(tenant_code,event_id))"
            )
            for operation in ("UPDATE", "DELETE"):
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS notification_delivery_no_{operation.lower()} BEFORE {operation} ON notification_delivery_event BEGIN SELECT RAISE(ABORT, 'append-only notification delivery history'); END"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS notification_delivery_tenant_event ON notification_delivery_event(tenant_code,event_id,sequence)"
            )
            conn.execute("BEGIN IMMEDIATE")
            # Migrate terminology, never reset the alert clock or filing references.
            for tenant, event_id, payload in conn.execute(
                "SELECT tenant_code,event_id,payload_json FROM notification_obligation"
            ).fetchall():
                row = json.loads(payload)
                for key in ("state", "reportability_status", "deadline_status"):
                    if row.get(key) == "UNRESOLVED":
                        row[key] = "UNKNOWN"
                conn.execute(
                    "UPDATE notification_obligation SET payload_json=? WHERE tenant_code=? AND event_id=?",
                    (json.dumps(row), tenant, event_id),
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
                "state": "PENDING" if clock.reportable else "UNKNOWN",
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
        """Privileged local DB/operator read. HTTP callers must use read_queue.

        Possession of the store is already filesystem-level access; this is not
        an authentication boundary. Never expose this helper directly remotely.
        """
        if not tenant_code or not tenant_code.strip():
            raise ValueError("tenant scope required")
        with self.store.connection() as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                "SELECT payload_json FROM notification_obligation WHERE tenant_code=? ORDER BY event_id", (tenant_code,)
            ).fetchall()
            result = []
            for record in rows:
                row = json.loads(record[0])
                history = [
                    json.loads(e[0])
                    for e in conn.execute(
                        "SELECT payload_json FROM notification_delivery_event WHERE tenant_code=? AND event_id=? ORDER BY sequence",
                        (tenant_code, row["event_id"]),
                    ).fetchall()
                ]
                attempts = [e for e in history if e["kind"] == "ATTEMPT"]
                acks = [e for e in history if e["kind"] == "ACK"]
                latest = attempts[-1] if attempts else None
                row["delivery_attempts"] = attempts
                row["acknowledgements"] = acks
                row["delivery_status"] = (
                    "NOT_ATTEMPTED"
                    if latest is None
                    else "ACK_RECORDED_UNVERIFIED"
                    if any(a["attempt_id"] == latest["attempt_id"] for a in acks)
                    else "RETRY_PENDING"
                    if latest["outcome"] == "FAILED"
                    else "AWAITING_ACK"
                )
                row["retry_at"] = latest.get("retry_at") if latest and latest["outcome"] == "FAILED" else None
                result.append(row)
        return result

    def read_queue(self, principal: NotificationPrincipal, tenant_code: str):
        principal.authorize(tenant_code)
        return self.queue(tenant_code)

    def record_delivery_attempt(
        self,
        principal: NotificationPrincipal,
        tenant_code: str,
        event_id: str,
        *,
        outcome: str,
        reference: str,
        retry_at: str | None = None,
    ):
        """Record an operator/adapter claim; does not send or schedule anything."""
        principal.authorize(tenant_code, write=True)
        if outcome not in {"FAILED", "SENT"} or not reference.strip():
            raise ValueError("FAILED/SENT and nonempty reference required")
        if retry_at is not None:
            when = datetime.fromisoformat(retry_at.replace("Z", "+00:00"))
            if when.tzinfo is None or outcome != "FAILED":
                raise ValueError("retry requires FAILED and an explicit timezone")
            retry_at = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        row = {
            "kind": "ATTEMPT",
            "attempt_id": uuid4().hex,
            "outcome": outcome,
            "reference": reference,
            "retry_at": retry_at,
            "actor": principal.subject,
            "recorded_at_utc": utc_now().isoformat() + "Z",
            "verification": "UNVERIFIED_DELIVERY_CLAIM",
        }
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_obligation(conn, tenant_code, event_id)
            conn.execute(
                "INSERT INTO notification_delivery_event(tenant_code,event_id,kind,payload_json) VALUES (?,?,?,?)",
                (tenant_code, event_id, "ATTEMPT", json.dumps(row)),
            )
        return row

    def record_delivery_acknowledgement(
        self, principal: NotificationPrincipal, tenant_code: str, event_id: str, attempt_id: str, reference: str
    ):
        """Receipt reference is not authenticated delivery, filing or legal clearance."""
        principal.authorize(tenant_code, write=True)
        if not reference.strip():
            raise ValueError("nonempty receipt reference required")
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_obligation(conn, tenant_code, event_id)
            history = [
                json.loads(e[0])
                for e in conn.execute(
                    "SELECT payload_json FROM notification_delivery_event WHERE tenant_code=? AND event_id=? ORDER BY sequence",
                    (tenant_code, event_id),
                ).fetchall()
            ]
            if not any(
                e["kind"] == "ATTEMPT" and e["attempt_id"] == attempt_id and e["outcome"] == "SENT" for e in history
            ):
                raise ValueError("acknowledgement requires this tenant/event's SENT attempt")
            existing = next((e for e in history if e["kind"] == "ACK" and e["attempt_id"] == attempt_id), None)
            if existing:
                if existing["reference"] != reference:
                    raise ValueError("conflicting acknowledgement reference")
                return existing
            row = {
                "kind": "ACK",
                "attempt_id": attempt_id,
                "reference": reference,
                "actor": principal.subject,
                "recorded_at_utc": utc_now().isoformat() + "Z",
                "verification": "UNVERIFIED_REFERENCE",
            }
            conn.execute(
                "INSERT INTO notification_delivery_event(tenant_code,event_id,kind,payload_json) VALUES (?,?,?,?)",
                (tenant_code, event_id, "ACK", json.dumps(row)),
            )
        return row

    @staticmethod
    def _require_obligation(conn, tenant_code: str, event_id: str):
        if not conn.execute(
            "SELECT 1 FROM notification_obligation WHERE tenant_code=? AND event_id=?", (tenant_code, event_id)
        ).fetchone():
            raise KeyError((tenant_code, event_id))

    def record_filing_reference(self, tenant_code: str, event_id: str, reference: str):
        """Privileged local reference, not a filing/clearance or remote API."""
        if not reference.strip():
            raise ValueError("nonempty filing reference required")
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
