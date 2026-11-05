#!/usr/bin/env python3
"""Kestrel Sentinel — single-file as-of adjudication & evidence platform.

Case-study submission by Zulfiqar Ali Ahmed — a working prototype of the hard as-of /
evidence path, organised as delimited modules inside one file (not a multi-service
production deploy).

Module layout (search the ====SECTION==== markers):
  CONFIG          — typed Settings
  LOGGING         — structured logging helpers
  EXCEPTIONS      — domain/API exception hierarchy
  DOMAIN          — enums + dataclasses (engine-safe; no Pydantic required)
  PACK / INGEST   — workbook memory model + bitemporal load
  REPOSITORY      — BitemporalStore, EvidenceStore
  RESOLUTION      — identity, SOP-as-of, stability, regulatory clock
  ENGINE          — pure deterministic adjudication (no I/O, no LLM, no randomness)
  LIFECYCLE       — case state machine + deadline-ordered queue
  SHADOW          — Dr Rao bulletin replay/diff
  SERVICES        — AdjudicationService façade (agreement, health, persist)
  API             — FastAPI app factory (lazy import; Pydantic v2 schemas)
  CLI             — argparse entrypoint
  TESTS           — embedded unittest suite

Dependencies:
  Required for engine/tests: openpyxl (+ Python stdlib).
  Required for `serve` / API TestClient: fastapi, pydantic>=2, uvicorn
  (httpx recommended for TestClient). Framework imports are lazy inside the API
  layer so `python kestrel.py test|run-all|…` still works with only openpyxl.

CLI:
  python kestrel.py ingest|adjudicate|run-all|basis|verify|replay|shadow-bulletin|queue|as-of-sop|health|monitor|agreement|serve|test|selftest
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import unittest
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

from openpyxl import load_workbook


# ====CONFIG====
# ====CONFIG====
_REPO_ROOT = Path(__file__).resolve().parent
_DEFAULT_PACK = _REPO_ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"


@dataclass
class Settings:
    """Runtime settings (env KESTREL_* optional; no third-party settings lib)."""

    data_pack: Path = field(default_factory=lambda: _DEFAULT_PACK)
    db_path: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "kestrel-adjudication" / "kestrel.sqlite")
    evidence_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "kestrel-adjudication" / "evidence")
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    rule_pack_version: str = "0.3.0"
    retention_years: int = 7
    code_version: str = "0.3.0"

    def __post_init__(self) -> None:
        """Normalize Path fields and apply optional KESTREL_* environment overrides."""
        self.data_pack = Path(self.data_pack)
        self.db_path = Path(self.db_path)
        self.evidence_dir = Path(self.evidence_dir)
        # Optional env overrides (stdlib only)
        env = os.environ
        if env.get("KESTREL_DATA_PACK"):
            self.data_pack = Path(env["KESTREL_DATA_PACK"])
        if env.get("KESTREL_DB_PATH"):
            self.db_path = Path(env["KESTREL_DB_PATH"])
        if env.get("KESTREL_EVIDENCE_DIR"):
            self.evidence_dir = Path(env["KESTREL_EVIDENCE_DIR"])
        if env.get("KESTREL_LOG_LEVEL"):
            self.log_level = env["KESTREL_LOG_LEVEL"]
        if env.get("KESTREL_API_HOST"):
            self.api_host = env["KESTREL_API_HOST"]
        if env.get("KESTREL_API_PORT"):
            self.api_port = int(env["KESTREL_API_PORT"])


def get_settings() -> Settings:
    """Return default Settings (fresh instance each call)."""
    return Settings()


# ====LOGGING====
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured stdout logging."""
    def format(self, record: logging.LogRecord) -> str:
        """Format a LogRecord as a single-line JSON object."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with a JSON formatter at the given level."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())



# ====EXCEPTIONS====


class KestrelError(Exception):
    """Base class for recoverable Kestrel domain/API errors."""


class NotFoundError(KestrelError):
    """Requested entity (event, bundle, SOP) was not found."""


class TenantIsolationError(KestrelError, PermissionError):
    """Cross-tenant access denied (Meridian Cl.22 / evidence isolation)."""


class ValidationAppError(KestrelError):
    """Caller supplied invalid input for an API or service operation."""


class DependencyMissingError(KestrelError):
    """Optional framework dependency (FastAPI/Pydantic/uvicorn) is not installed."""


# ====DOMAIN====
from enum import Enum


class Disposition(str, Enum):
    """Allowed disposition / recommendation values for an excursion case."""
    AUTO_CLOSE = "AUTO_CLOSE"
    RELEASE = "RELEASE"
    RELEASE_WITH_NOTE = "RELEASE_WITH_NOTE"
    QUARANTINE_PENDING_LAB = "QUARANTINE_PENDING_LAB"
    DESTROY = "DESTROY"
    RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"
    REWORK_RELABEL = "REWORK_RELABEL"
    ESCALATED_TO_SENIOR_QA = "ESCALATED_TO_SENIOR_QA"


ACTIONABLE = {
    Disposition.RELEASE,
    Disposition.RELEASE_WITH_NOTE,
    Disposition.QUARANTINE_PENDING_LAB,
    Disposition.DESTROY,
    Disposition.RETURN_TO_ORIGIN,
    Disposition.REWORK_RELABEL,
    Disposition.ESCALATED_TO_SENIOR_QA,
}


class CaseState(str, Enum):
    """Case lifecycle states from NEW through CLOSED_* and REOPENED."""
    NEW = "NEW"
    TRIAGED_NON_ACTIONABLE = "TRIAGED_NON_ACTIONABLE"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    RECOMMENDED = "RECOMMENDED"
    AWAITING_REVIEWER = "AWAITING_REVIEWER"
    RETURNED_FOR_DATA = "RETURNED_FOR_DATA"
    PENDING_LAB = "PENDING_LAB"
    PENDING_SECOND_SIGN = "PENDING_SECOND_SIGN"
    CLOSED_AUTO = "CLOSED_AUTO"
    CLOSED_SIGNED = "CLOSED_SIGNED"
    REOPENED = "REOPENED"


class TransitionError(ValueError):
    """Raised when a case state transition is not in the ALLOWED map."""
    pass


# ====MODELS====
# Lightweight domain DTOs (stdlib dataclasses; no pydantic).


@dataclass
class Alert:
    """Excursion alert row shape used by API/docs; engine uses pack dicts."""

    event_id: str
    tenant_code: str
    alert_ts_utc: Optional[datetime] = None
    excursion_start_utc: Optional[datetime] = None
    excursion_end_utc: Optional[datetime] = None
    duration_min: Optional[float] = None
    min_temp_c: Optional[float] = None
    max_temp_c: Optional[float] = None
    mean_temp_c: Optional[float] = None
    product_ref_as_received: Optional[str] = None
    origin_ref_as_received: Optional[str] = None
    dest_ref_as_received: Optional[str] = None
    carrier_ref_as_received: Optional[str] = None
    lane_text: Optional[str] = None
    logger_fw: Optional[str] = None
    logger_id: Optional[str] = None
    spec_text_as_received: Optional[str] = None
    gateway_gap_min: Optional[float] = None
    interpolated: Optional[str] = None
    dock_door_open_flag: Optional[str] = None
    prior_excursions_lane_90d: Optional[int] = None
    consignment_value_usd: Optional[float] = None
    triage_outcome: Optional[str] = None
    rules_engine_recommendation: Optional[str] = None
    final_disposition: Optional[str] = None
    regulator_reportable: Optional[str] = None
    reg_window_hours: Optional[float] = None
    shipment_ref: Optional[str] = None
    source_system: Optional[str] = None
    notes: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recommendation:
    """Structured disposition recommendation emitted alongside evidence."""

    event_id: str
    tenant_code: str
    disposition: Disposition
    requires_human_signature: bool
    confidence: float
    triage_label: str
    rationale: list[str] = field(default_factory=list)
    evidence_outline: dict[str, Any] = field(default_factory=dict)
    product_match_method: Optional[str] = None
    product_sku: Optional[str] = None
    product_brand: Optional[str] = None
    stability_study_ref: Optional[str] = None
    sop_doc_id: Optional[str] = None
    sop_revision: Optional[str] = None
    sop_overlap_conflict: bool = False
    carrier_contract_id: Optional[str] = None
    carrier_has_cold_chain_clause: Optional[bool] = None
    corrected_max_temp_c: Optional[float] = None
    bulletin_applied: bool = False
    regulator_reportable: bool = False
    reg_window_hours: Optional[float] = None
    reg_deadline_utc: Optional[datetime] = None
    rule_pack_version: str = "0.3.0"
    ref_snapshot_id: Optional[str] = None
    code_version: str = "0.3.0"


@dataclass
class Case:
    """Lifecycle case record (also persisted via BitemporalStore)."""

    case_id: str
    event_id: str
    tenant_code: str
    state: CaseState = CaseState.NEW
    recommendation: Optional[Disposition] = None
    final_disposition: Optional[Disposition] = None
    evidence_bundle_id: Optional[str] = None
    reg_deadline_utc: Optional[datetime] = None
    regulator_reportable: bool = False
    priority_score: float = 0.0
    reopened_from_case_id: Optional[str] = None
    reopen_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    signed_by: Optional[str] = None
    signed_at: Optional[datetime] = None


@dataclass
class EvidenceBundleMeta:
    """Hash-chain metadata for an append-only evidence bundle."""

    bundle_id: str
    content_hash: str
    prev_hash: Optional[str]
    tenant_code: str
    event_id: str
    case_id: Optional[str] = None
    created_at: Optional[datetime] = None
    retention_until: Optional[datetime] = None
    rule_pack_version: str = "0.3.0"
    ref_snapshot_id: str = ""
    code_version: str = "0.3.0"


# ====PACK====
"""Load the KCCS Sentinel Reference Data Pack workbook into memory."""


from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime-like value into a naive datetime, or None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(value: Any) -> Optional[date]:
    """Parse a date-like value into a date, or None if unparseable."""
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _rows(ws: Any) -> list[dict[str, Any]]:
    """Read an openpyxl worksheet into a list of header-keyed dict rows."""
    headers = [c.value for c in ws[1]]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None and all(v is None for v in row):
            continue
        out.append({headers[i]: row[i] for i in range(len(headers))})
    return out


@dataclass
class DataPack:
    """In-memory view of the case-study workbook sheets used by the engine."""
    path: Path
    events: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    facilities: list[dict[str, Any]] = field(default_factory=list)
    carriers: list[dict[str, Any]] = field(default_factory=list)
    sops: list[dict[str, Any]] = field(default_factory=list)
    stability: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[dict[str, Any]] = field(default_factory=list)
    overrides: list[dict[str, Any]] = field(default_factory=list)
    tenants: list[dict[str, Any]] = field(default_factory=list)
    incidents: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | str) -> "DataPack":
        """Load all relevant sheets from the Excel pack into a DataPack."""
        path = Path(path)
        wb = load_workbook(path, data_only=True, read_only=True)
        pack = cls(path=path)
        pack.events = _rows(wb["01_Excursion_Events"])
        pack.products = _rows(wb["02_Product_Master"])
        pack.facilities = _rows(wb["03_Facility_Registry"])
        pack.carriers = _rows(wb["04_Carrier_Contracts"])
        pack.sops = _rows(wb["05_SOP_Index"])
        pack.stability = _rows(wb["06_Stability_Index"])
        pack.aliases = _rows(wb["07_Alias_Observations"])
        pack.overrides = _rows(wb["09_Override_Reasons"])
        pack.tenants = [
            r for r in _rows(wb["12_Tenant_Constraints"]) if r.get("tenant_code") and str(r["tenant_code"]).startswith("T-")
        ]
        pack.incidents = _rows(wb["14_Incident_Log"])
        wb.close()
        # Normalize a few fields used heavily
        for e in pack.events:
            e["_alert_ts"] = _parse_dt(e.get("alert_ts_utc"))
            e["_excursion_start"] = _parse_dt(e.get("excursion_start_utc"))
            e["_excursion_end"] = _parse_dt(e.get("excursion_end_utc"))
        for s in pack.sops:
            s["_effective_from"] = _parse_date(s.get("effective_from"))
            s["_effective_to"] = _parse_date(s.get("effective_to"))
        for c in pack.carriers:
            c["_effective_from"] = _parse_date(c.get("effective_from"))
            to = c.get("effective_to")
            if to is None or str(to).lower() in {"evergreen", ""}:
                c["_effective_to"] = None
            else:
                c["_effective_to"] = _parse_date(to)
        return pack

    def event_by_id(self, event_id: str) -> Optional[dict[str, Any]]:
        """Return the excursion event dict for event_id, or None."""
        for e in self.events:
            if e.get("event_id") == event_id:
                return e
        return None


# ====WORKBOOK====
"""Workbook loader adapter — loads the real pack into the bitemporal store."""


import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from openpyxl import load_workbook


log = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime-like value into a naive datetime, or None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(value: Any) -> Optional[date]:
    """Parse a date-like value into a date, or None if unparseable."""
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _rows(ws: Any) -> list[dict[str, Any]]:
    """Read an openpyxl worksheet into a list of header-keyed dict rows."""
    headers = [c.value for c in ws[1]]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if all(v is None for v in row):
            continue
        out.append({headers[i]: row[i] for i in range(len(headers))})
    return out


def load_workbook_into_store(
    pack_path: Path | str,
    store: BitemporalStore,
    *,
    snapshot_id: Optional[str] = None,
    tx_from: Optional[datetime] = None,
) -> str:
    """Ingest workbook reference data and alerts into the bitemporal store; return snapshot id."""
    pack_path = Path(pack_path)
    snapshot_id = snapshot_id or f"snap-{uuid4().hex[:12]}"
    tx_from = tx_from or datetime(2026, 9, 14)  # extract date from pack README
    wb = load_workbook(pack_path, data_only=True, read_only=True)

    # Products
    for p in _rows(wb["02_Product_Master"]):
        tenant = p.get("tenant_code")
        key = str(p.get("gtin") or p.get("internal_sku") or p.get("brand_as_labelled") or id(p))
        store.insert_ref(
            entity_type="product",
            tenant_code=tenant,
            natural_key=f"{tenant}:{key}",
            payload=p,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system=str(p.get("erp_source") or "ERP"),
        )

    # SOPs — each revision is a valid-time version
    for s in _rows(wb["05_SOP_Index"]):
        ef = _parse_date(s.get("effective_from")) or date(2020, 1, 1)
        et = _parse_date(s.get("effective_to"))
        store.insert_ref(
            entity_type="sop",
            tenant_code=s.get("tenant_code"),
            natural_key=f"{s.get('doc_id')}:{s.get('revision')}",
            payload=s,
            valid_from=ef,
            valid_to=et,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-07",
        )

    # Stability
    for s in _rows(wb["06_Stability_Index"]):
        store.insert_ref(
            entity_type="stability",
            tenant_code=s.get("tenant_code"),
            natural_key=str(s.get("study_ref")),
            payload=s,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-06",
        )

    # Carriers
    for c in _rows(wb["04_Carrier_Contracts"]):
        ef = _parse_date(c.get("effective_from")) or date(2019, 1, 1)
        to_raw = c.get("effective_to")
        et = None if to_raw is None or str(to_raw).lower() == "evergreen" else _parse_date(to_raw)
        store.insert_ref(
            entity_type="carrier_contract",
            tenant_code=None,
            natural_key=str(c.get("contract_id")),
            payload=c,
            valid_from=ef,
            valid_to=et,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-08",
        )

    # Aliases
    for a in _rows(wb["07_Alias_Observations"]):
        store.insert_ref(
            entity_type="alias",
            tenant_code=None,
            natural_key=f"{a.get('entity_kind')}:{a.get('string_a')}:{a.get('string_b')}",
            payload=a,
            valid_from=_parse_date(a.get("confirmed_on")) or date(2025, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="reviewer",
        )

    # Tenants
    for t in _rows(wb["12_Tenant_Constraints"]):
        code = t.get("tenant_code")
        if not code or not str(code).startswith("T-"):
            continue
        store.insert_ref(
            entity_type="tenant",
            tenant_code=str(code),
            natural_key=str(code),
            payload=t,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="commercial",
        )

    # Alerts
    n = 0
    for e in _rows(wb["01_Excursion_Events"]):
        eid = e.get("event_id")
        if not eid:
            continue
        e = dict(e)
        e["_alert_ts"] = _parse_dt(e.get("alert_ts_utc"))
        e["_excursion_start"] = _parse_dt(e.get("excursion_start_utc"))
        e["_excursion_end"] = _parse_dt(e.get("excursion_end_utc"))
        # serialize datetimes for JSON
        payload = {k: (v.isoformat(sep=" ") if isinstance(v, datetime) else v) for k, v in e.items()}
        payload["_alert_ts"] = e["_alert_ts"].isoformat(sep=" ") if e["_alert_ts"] else None
        payload["_excursion_start"] = (
            e["_excursion_start"].isoformat(sep=" ") if e["_excursion_start"] else None
        )
        store.upsert_alert(str(eid), str(e.get("tenant_code") or ""), payload, snapshot_id)
        n += 1

    wb.close()
    store.set_meta("ref_snapshot_id", snapshot_id)
    store.set_meta("pack_path", str(pack_path))
    store.set_meta("loaded_alerts", str(n))
    log.info("loaded workbook", extra={"extra_fields": {"snapshot_id": snapshot_id, "alerts": n}})
    return snapshot_id


# ====STORE====
"""SQLite bitemporal reference store.

valid_from / valid_to  = when true in the world (SOP effective dates, contract term)
tx_from / tx_to        = when Sentinel believed it (ingestion / correction)
"""


import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_record (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  tenant_code TEXT,
  natural_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  tx_from TEXT NOT NULL,
  tx_to TEXT,
  content_hash TEXT NOT NULL,
  source_system TEXT,
  snapshot_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ref_lookup
  ON ref_record(entity_type, tenant_code, natural_key, valid_from, tx_from);

CREATE TABLE IF NOT EXISTS alert (
  event_id TEXT PRIMARY KEY,
  tenant_code TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  alert_ts_utc TEXT,
  snapshot_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_row (
  case_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  tenant_code TEXT NOT NULL,
  state TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  reg_deadline_utc TEXT,
  priority_score REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_queue
  ON case_row(tenant_code, state, reg_deadline_utc, priority_score);

CREATE TABLE IF NOT EXISTS evidence_index (
  bundle_id TEXT PRIMARY KEY,
  tenant_code TEXT NOT NULL,
  event_id TEXT NOT NULL,
  case_id TEXT,
  content_hash TEXT NOT NULL,
  prev_hash TEXT,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  retention_until TEXT NOT NULL,
  rule_pack_version TEXT NOT NULL,
  ref_snapshot_id TEXT NOT NULL,
  code_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_tenant_event
  ON evidence_index(tenant_code, event_id);
"""


def _utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(d: date | datetime | None) -> Optional[str]:
    """Serialize a date/datetime to an ISO-ish string, or None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.isoformat(sep=" ")
    return d.isoformat()


def _parse_date(s: Optional[str]) -> Optional[date]:
    """Parse a date-like value into a date, or None if unparseable."""
    if not s:
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse a datetime-like value into a naive datetime, or None if unparseable."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt) if len(s) >= 19 or " " in s or "T" in s else datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class BitemporalStore:
    """SQLite store with valid-time and transaction-time axes for reference data, cases, and evidence index."""
    def __init__(self, path: Path | str) -> None:
        """Open (or create) the SQLite database at path and ensure schema exists."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with foreign keys and row factory enabled."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager yielding a connection that commits on success."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        """Create tables and indexes if they do not already exist."""
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def set_meta(self, key: str, value: str) -> None:
        """Upsert a string metadata key/value on the store."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
        """Return a metadata value by key, or None."""
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def insert_ref(
        self,
        *,
        entity_type: str,
        natural_key: str,
        payload: dict[str, Any],
        valid_from: date | datetime,
        snapshot_id: str,
        tenant_code: Optional[str] = None,
        valid_to: date | datetime | None = None,
        tx_from: datetime | None = None,
        source_system: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> str:
        """Insert a bitemporal reference row; return its record id."""
        import hashlib

        tx_from = tx_from or _utcnow()
        body = json.dumps(payload, sort_keys=True, default=str)
        content_hash = content_hash or hashlib.sha256(body.encode()).hexdigest()
        rid = str(uuid4())
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO ref_record(
                    id, entity_type, tenant_code, natural_key, payload_json,
                    valid_from, valid_to, tx_from, tx_to, content_hash, source_system, snapshot_id
                ) VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?)""",
                (
                    rid,
                    entity_type,
                    tenant_code,
                    natural_key,
                    body,
                    _iso(valid_from),
                    _iso(valid_to),
                    _iso(tx_from),
                    content_hash,
                    source_system,
                    snapshot_id,
                ),
            )
        return rid

    def as_of(
        self,
        *,
        entity_type: str,
        natural_key: Optional[str] = None,
        tenant_code: Optional[str] = None,
        valid_as_of: date | datetime,
        tx_as_of: date | datetime | None = None,
        title_contains: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return reference rows true at valid_as_of as known at tx_as_of."""
        tx_as_of = tx_as_of or _utcnow()
        v = _iso(valid_as_of if isinstance(valid_as_of, date) and not isinstance(valid_as_of, datetime) else (valid_as_of.date() if isinstance(valid_as_of, datetime) else valid_as_of))
        t = _iso(tx_as_of if isinstance(tx_as_of, datetime) else datetime.combine(tx_as_of, datetime.min.time()))
        assert v and t
        clauses = [
            "entity_type = ?",
            "valid_from <= ?",
            "(valid_to IS NULL OR valid_to >= ?)",
            "tx_from <= ?",
            "(tx_to IS NULL OR tx_to > ?)",
        ]
        params: list[Any] = [entity_type, v, v, t, t]
        if tenant_code is not None:
            clauses.append("tenant_code = ?")
            params.append(tenant_code)
        if natural_key is not None:
            clauses.append("natural_key = ?")
            params.append(natural_key)
        sql = f"SELECT * FROM ref_record WHERE {' AND '.join(clauses)} ORDER BY valid_from DESC, tx_from DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            payload = json.loads(r["payload_json"])
            if title_contains and title_contains.lower() not in str(payload.get("title") or "").lower():
                continue
            out.append(
                {
                    "id": r["id"],
                    "entity_type": r["entity_type"],
                    "tenant_code": r["tenant_code"],
                    "natural_key": r["natural_key"],
                    "payload": payload,
                    "valid_from": r["valid_from"],
                    "valid_to": r["valid_to"],
                    "tx_from": r["tx_from"],
                    "tx_to": r["tx_to"],
                    "content_hash": r["content_hash"],
                    "snapshot_id": r["snapshot_id"],
                }
            )
        return out

    def sop_in_force(
        self,
        tenant_code: str,
        title_contains: str,
        valid_as_of: date,
        tx_as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Return the SOP revision(s) in force for tenant/title at valid_as_of (and tx_as_of)."""
        rows = self.as_of(
            entity_type="sop",
            tenant_code=tenant_code,
            valid_as_of=valid_as_of,
            tx_as_of=tx_as_of,
            title_contains=title_contains,
        )
        # Also match by scanning natural keys when title filter applied above
        if not rows:
            rows = [
                r
                for r in self.as_of(
                    entity_type="sop",
                    tenant_code=tenant_code,
                    valid_as_of=valid_as_of,
                    tx_as_of=tx_as_of,
                )
                if title_contains.lower() in str(r["payload"].get("title") or "").lower()
            ]
        if not rows:
            return {"record": None, "overlap_conflict": False, "competing": []}

        def rev_key(r: dict[str, Any]) -> int:
            rev = str(r["payload"].get("revision") or "")
            digits = "".join(ch for ch in rev if ch.isdigit())
            return int(digits) if digits else 0

        # Group by doc_id
        by_doc: dict[str, list] = {}
        for r in rows:
            by_doc.setdefault(str(r["payload"].get("doc_id")), []).append(r)
        # Prefer docs matching title; pick highest rev among all matching
        rows.sort(key=rev_key, reverse=True)
        competing = rows
        overlap = len({(r["payload"].get("doc_id"), r["payload"].get("revision")) for r in rows}) > 1
        return {"record": rows[0], "overlap_conflict": overlap, "competing": competing}

    def upsert_alert(self, event_id: str, tenant_code: str, payload: dict[str, Any], snapshot_id: str) -> None:
        """Insert or replace a packed alert payload keyed by event_id."""
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO alert(event_id, tenant_code, payload_json, alert_ts_utc, snapshot_id)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(event_id) DO UPDATE SET
                     payload_json=excluded.payload_json,
                     tenant_code=excluded.tenant_code,
                     alert_ts_utc=excluded.alert_ts_utc,
                     snapshot_id=excluded.snapshot_id""",
                (
                    event_id,
                    tenant_code,
                    json.dumps(payload, default=str),
                    str(payload.get("alert_ts_utc") or ""),
                    snapshot_id,
                ),
            )

    def get_alert(self, event_id: str) -> Optional[dict[str, Any]]:
        """Fetch one alert payload by event_id."""
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alert WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["payload_json"])

    def list_alerts(self, tenant_code: Optional[str] = None) -> list[dict[str, Any]]:
        """List alert payloads, optionally filtered by tenant_code."""
        with self.connection() as conn:
            if tenant_code:
                rows = conn.execute(
                    "SELECT payload_json FROM alert WHERE tenant_code=? ORDER BY event_id",
                    (tenant_code,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM alert ORDER BY event_id").fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def save_case(self, case: dict[str, Any]) -> None:
        """Insert or update a case lifecycle record."""
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO case_row(case_id, event_id, tenant_code, state, payload_json, reg_deadline_utc, priority_score, updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(case_id) DO UPDATE SET
                     state=excluded.state,
                     payload_json=excluded.payload_json,
                     reg_deadline_utc=excluded.reg_deadline_utc,
                     priority_score=excluded.priority_score,
                     updated_at=excluded.updated_at""",
                (
                    case["case_id"],
                    case["event_id"],
                    case["tenant_code"],
                    case["state"],
                    json.dumps(case, default=str),
                    case.get("reg_deadline_utc"),
                    float(case.get("priority_score") or 0),
                    case.get("updated_at") or _iso(_utcnow()),
                ),
            )

    def get_case(self, case_id: str) -> Optional[dict[str, Any]]:
        """Fetch a case dict by case_id."""
        with self.connection() as conn:
            row = conn.execute("SELECT payload_json FROM case_row WHERE case_id=?", (case_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def queue(
        self,
        *,
        tenant_code: Optional[str] = None,
        open_only: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Priority queue: earliest regulatory deadline first (storm-safe ordering)."""
        closed = ("CLOSED_AUTO", "CLOSED_SIGNED")
        clauses = []
        params: list[Any] = []
        if tenant_code:
            clauses.append("tenant_code = ?")
            params.append(tenant_code)
        if open_only:
            placeholders = ",".join("?" for _ in closed)
            clauses.append(f"state NOT IN ({placeholders})")
            params.extend(closed)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""SELECT payload_json FROM case_row{where}
                  ORDER BY
                    CASE WHEN reg_deadline_utc IS NULL OR reg_deadline_utc='' THEN 1 ELSE 0 END,
                    reg_deadline_utc ASC,
                    priority_score DESC,
                    updated_at ASC
                  LIMIT ?"""
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def index_evidence(self, meta: dict[str, Any]) -> None:
        """Index evidence-bundle metadata for hash-chain and retrieval queries."""
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO evidence_index(
                    bundle_id, tenant_code, event_id, case_id, content_hash, prev_hash,
                    path, created_at, retention_until, rule_pack_version, ref_snapshot_id, code_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    meta["bundle_id"],
                    meta["tenant_code"],
                    meta["event_id"],
                    meta.get("case_id"),
                    meta["content_hash"],
                    meta.get("prev_hash"),
                    meta["path"],
                    meta["created_at"],
                    meta["retention_until"],
                    meta["rule_pack_version"],
                    meta["ref_snapshot_id"],
                    meta["code_version"],
                ),
            )

    def get_evidence_meta(self, bundle_id: str, tenant_code: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Fetch evidence metadata by bundle_id (optional tenant filter)."""
        with self.connection() as conn:
            if tenant_code:
                row = conn.execute(
                    "SELECT * FROM evidence_index WHERE bundle_id=? AND tenant_code=?",
                    (bundle_id, tenant_code),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM evidence_index WHERE bundle_id=?", (bundle_id,)
                ).fetchone()
        return dict(row) if row else None

    def evidence_for_event(self, event_id: str, tenant_code: str) -> list[dict[str, Any]]:
        """List evidence metadata rows for an event within a tenant."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_index WHERE event_id=? AND tenant_code=? ORDER BY created_at",
                (event_id, tenant_code),
            ).fetchall()
        return [dict(r) for r in rows]

    def chain_for_tenant(self, tenant_code: str) -> list[dict[str, Any]]:
        """Return evidence chain rows for a tenant in append order."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_index WHERE tenant_code=? ORDER BY created_at, bundle_id",
                (tenant_code,),
            ).fetchall()
        return [dict(r) for r in rows]


# ====AS_OF====
"""Bitemporal-ish 'as at a date' lookups for SOPs and contracts.

We only have valid-time in the pack (effective_from / effective_to). Transaction
time is stubbed: the extract itself is the snapshot. Design doc describes the
full bitemporal model for production.
"""


from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


@dataclass
class AsOfHit:
    """Result of an as-of SOP lookup: selected record, overlap flag, and competitors."""
    record: dict[str, Any]
    overlap_conflict: bool
    competing: list[dict[str, Any]]


def sop_in_force(
    sops: list[dict[str, Any]],
    tenant_code: str,
    title_contains: str,
    as_of: date,
) -> AsOfHit | None:
    """Select the SOP revision in force from an in-memory SOP list at as_of (highest rev on overlap)."""
    title_l = title_contains.lower()
    candidates = []
    for s in sops:
        if s.get("tenant_code") != tenant_code:
            continue
        if title_l not in str(s.get("title") or "").lower():
            continue
        ef, et = s.get("_effective_from"), s.get("_effective_to")
        if ef is None:
            continue
        if ef <= as_of and (et is None or as_of <= et):
            candidates.append(s)
    if not candidates:
        # Also try open-ended where effective_to blank and from <= as_of
        for s in sops:
            if s.get("tenant_code") != tenant_code:
                continue
            if title_l not in str(s.get("title") or "").lower():
                continue
            ef, et = s.get("_effective_from"), s.get("_effective_to")
            if ef and ef <= as_of and et is None:
                candidates.append(s)
    # de-dupe by (doc_id, revision)
    uniq = {}
    for c in candidates:
        uniq[(c.get("doc_id"), c.get("revision"))] = c
    candidates = list(uniq.values())
    if not candidates:
        return None
    # Prefer highest revision number when overlap
    def rev_key(r: dict[str, Any]) -> int:
        rev = str(r.get("revision") or "")
        digits = "".join(ch for ch in rev if ch.isdigit())
        return int(digits) if digits else 0

    candidates.sort(key=rev_key, reverse=True)
    return AsOfHit(
        record=candidates[0],
        overlap_conflict=len(candidates) > 1,
        competing=candidates,
    )


def parse_storage_range(spec_text: Any) -> tuple[Optional[float], Optional[float]]:
    """Best-effort parse of free-text labelled storage range -> (low, high) °C."""
    if not spec_text:
        return None, None
    import re

    s = str(spec_text)
    s_l = s.lower()
    if "ln2" in s_l or "vapour" in s_l or "vapor" in s_l or "≤ -150" in s or "<= -150" in s_l:
        return -196.0, -150.0
    if "ultra-cold" in s_l or re.search(r"-80\s*/\s*-60", s) or "-80/-60" in s.replace(" ", ""):
        m = re.search(r"(-?\d+)\s*/\s*(-?\d+)", s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            return min(a, b), max(a, b)
        return -80.0, -60.0
    if re.search(r"-25\s*/?\s*-15|-25/-15", s.replace(" ", "")):
        return -25.0, -15.0
    # Prefer explicit range patterns before bare number extraction so "2-8" is
    # not parsed as (-8, 2) via a leading-minus token.
    m = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*[–\-~/to]+\s*(\d+(?:\.\d+)?)\s*°?\s*c?",
        s_l,
    )
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b)
    m = re.search(r"\+?(\d+)\s*/\s*\+?(\d+)", s)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b)
    if "crt" in s_l:
        return 15.0, 25.0
    if "below 25" in s_l:
        return None, 25.0
    return None, None


# ====IDENTITY====
"""Resolve messy product / facility / carrier strings to canonical entities."""


from dataclasses import dataclass, field
from typing import Any, Optional



@dataclass
class ResolvedProduct:
    """Product identity resolution result with match method, confidence, and stability study ref."""
    tenant_code: str
    match_method: str
    confidence: float
    brand: Optional[str] = None
    generic_inn: Optional[str] = None
    internal_sku: Optional[str] = None
    gtin: Optional[str] = None
    storage_spec_text: Optional[str] = None
    permitted_excursion_text: Optional[str] = None
    stability_study_ref: Optional[str] = None
    light_sensitive: Optional[str] = None
    presentation_hint: Optional[str] = None  # pen / vial / pfs when guessable
    candidates: list[dict[str, Any]] = field(default_factory=list)
    unresolved_reason: Optional[str] = None


def _norm(s: Any) -> str:
    """Normalize free text for fuzzy matching (lowercase, collapse whitespace)."""
    if s is None:
        return ""
    return " ".join(str(s).strip().lower().replace("_", " ").split())


def _presentation_from_text(text: str) -> Optional[str]:
    """Infer presentation (pen/vial/etc.) from brand or study text, if possible."""
    t = _norm(text)
    if "pre-filled" in t or "pfs" in t or "syringe" in t:
        return "pfs"
    if "pen" in t or "solojet" in t:
        return "pen"
    if "vial" in t:
        return "vial"
    if "tabs" in t or "tablet" in t or "sachet" in t:
        return "oral"
    return None


class IdentityResolver:
    """Map product_ref_as_received (+ tenant) onto 02_Product_Master rows.

    Uses GTIN / SKU / brand / INN exact match, then alias observations for
    PRODUCT kind, then fuzzy brand containment. Never invents a product.
    """

    def __init__(self, pack: DataPack) -> None:
        """Bind the resolver to a loaded DataPack."""
        self.pack = pack
        self._alias_pairs: dict[str, set[str]] = {}
        for a in pack.aliases:
            if str(a.get("entity_kind") or "").upper() != "PRODUCT":
                continue
            if str(a.get("same_real_world_thing") or "").upper() != "Y":
                continue
            sa, sb = _norm(a.get("string_a")), _norm(a.get("string_b"))
            if not sa or not sb:
                continue
            self._alias_pairs.setdefault(sa, set()).add(sb)
            self._alias_pairs.setdefault(sb, set()).add(sa)

    def _product_strings(self, p: dict[str, Any]) -> set[str]:
        """Collect normalized identity strings from a product-master row."""
        keys = []
        for k in ("brand_as_labelled", "generic_inn", "internal_sku", "gtin", "legacy_code"):
            v = p.get(k)
            if v:
                keys.append(_norm(v))
        return set(keys)

    def resolve_product(self, tenant_code: str, product_ref: Any) -> ResolvedProduct:
        """Resolve a product_ref string to a canonical product for the tenant."""
        ref = (product_ref or "").strip() if product_ref else ""
        if not ref:
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="unresolved",
                confidence=0.0,
                unresolved_reason="blank product_ref_as_received",
            )

        ref_n = _norm(ref)
        tenant_products = [p for p in self.pack.products if p.get("tenant_code") == tenant_code]
        pool = tenant_products or list(self.pack.products)

        # 1. Exact GTIN
        for p in pool:
            if p.get("gtin") and _norm(p.get("gtin")) == ref_n:
                return self._from_row(p, "gtin_exact", 0.98)

        # 2. Exact SKU
        for p in pool:
            if p.get("internal_sku") and _norm(p.get("internal_sku")) == ref_n:
                return self._from_row(p, "sku_exact", 0.95)

        # 3. Exact brand / INN
        for p in pool:
            for field_name, conf in (("brand_as_labelled", 0.9), ("generic_inn", 0.85)):
                if p.get(field_name) and _norm(p.get(field_name)) == ref_n:
                    return self._from_row(p, f"{field_name}_exact", conf)

        # 4. Alias expansion then re-match
        expanded = {ref_n} | self._alias_pairs.get(ref_n, set())
        for alias in list(expanded):
            expanded |= self._alias_pairs.get(alias, set())
        for p in pool:
            strings = self._product_strings(p)
            if strings & expanded:
                return self._from_row(p, "alias_chain", 0.8)

        # 5. Brand containment (e.g. "Glucodyne 100U" vs "Glucodyne SoloJet 100U")
        hits = []
        for p in pool:
            brand = _norm(p.get("brand_as_labelled"))
            if brand and (brand in ref_n or ref_n in brand):
                hits.append(p)
            elif p.get("generic_inn") and _norm(p.get("generic_inn")) in ref_n:
                hits.append(p)
        if len(hits) == 1:
            return self._from_row(hits[0], "brand_containment", 0.7)
        if len(hits) > 1:
            # Prefer rows whose presentation matches ref
            hint = _presentation_from_text(ref)
            if hint:
                narrowed = [
                    h
                    for h in hits
                    if _presentation_from_text(
                        " ".join(
                            str(h.get(k) or "")
                            for k in ("brand_as_labelled", "generic_inn", "internal_sku")
                        )
                    )
                    == hint
                    or hint in _norm(h.get("brand_as_labelled"))
                ]
                if len(narrowed) == 1:
                    return self._from_row(narrowed[0], "brand_containment_presentation", 0.75)
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="ambiguous",
                confidence=0.4,
                candidates=hits[:5],
                unresolved_reason=f"ambiguous product match for {ref!r}: {len(hits)} candidates",
                presentation_hint=_presentation_from_text(ref),
            )

        return ResolvedProduct(
            tenant_code=tenant_code,
            match_method="unresolved",
            confidence=0.0,
            unresolved_reason=f"no product master match for {ref!r} under {tenant_code}",
            presentation_hint=_presentation_from_text(ref),
        )

    def _from_row(self, p: dict[str, Any], method: str, confidence: float) -> ResolvedProduct:
        """Build a ResolvedProduct from a product-master row and match metadata."""
        brand = p.get("brand_as_labelled")
        return ResolvedProduct(
            tenant_code=p.get("tenant_code") or "",
            match_method=method,
            confidence=confidence,
            brand=brand,
            generic_inn=p.get("generic_inn"),
            internal_sku=p.get("internal_sku"),
            gtin=str(p.get("gtin")) if p.get("gtin") else None,
            storage_spec_text=p.get("storage_spec_text"),
            permitted_excursion_text=p.get("permitted_excursion_text"),
            stability_study_ref=p.get("stability_study_ref"),
            light_sensitive=p.get("light_sensitive"),
            presentation_hint=_presentation_from_text(str(brand or "")),
            candidates=[p],
        )

    def resolve_facility_canonical(self, ref: Any) -> Optional[str]:
        """Return a preferred facility code if aliases map the string."""
        if not ref:
            return None
        ref_n = _norm(ref)
        # Prefer code_in_source exact
        for f in self.pack.facilities:
            if _norm(f.get("code_in_source")) == ref_n or _norm(f.get("name_in_source")) == ref_n:
                return str(f.get("code_in_source"))
        for a in self.pack.aliases:
            if str(a.get("entity_kind") or "").upper() != "FACILITY":
                continue
            if str(a.get("same_real_world_thing") or "").upper() != "Y":
                continue
            if _norm(a.get("string_a")) == ref_n:
                return str(a.get("string_a"))
            if _norm(a.get("string_b")) == ref_n:
                return str(a.get("string_a"))
        return str(ref)

    def resolve_carrier_contract(self, carrier_ref: Any, as_of: Optional[date] = None) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Resolve a carrier alias to the contract row in force on as_of."""
        from datetime import date as date_cls

        as_of = as_of or date_cls.today()
        if not carrier_ref:
            return None, "blank carrier_ref"
        ref_n = _norm(carrier_ref)
        matches = []
        for c in self.pack.carriers:
            names = [n.strip() for n in str(c.get("names_seen_on_documents") or "").split("|")]
            name_norms = {_norm(n) for n in names if n}
            legal = _norm(c.get("counterparty_legal_entity"))
            if ref_n == legal or ref_n in name_norms or any(ref_n in n or n in ref_n for n in name_norms if n):
                ef, et = c.get("_effective_from"), c.get("_effective_to")
                if ef and as_of < ef:
                    continue
                if et and as_of > et:
                    continue
                matches.append(c)
        if not matches:
            return None, f"no contract for carrier {carrier_ref!r} as of {as_of}"
        if len(matches) > 1:
            # Prefer longest name overlap / more specific legal entity
            matches.sort(key=lambda c: len(str(c.get("counterparty_legal_entity") or "")), reverse=True)
        return matches[0], None


# late import type
from datetime import date  # noqa: E402


# ====STABILITY====
"""Resolve stability / permitted excursion allowance for a product as cited."""


import re
from dataclasses import dataclass
from typing import Any, Optional



@dataclass
class StabilityPosition:
    """Parsed stability allowance for a resolved product (readable text, caps, flags)."""
    study_ref: Optional[str]
    permitted_text: Optional[str]
    readable: bool
    source: str  # product_master | stability_index | both | none
    max_temp_c: Optional[float] = None
    max_duration_hours: Optional[float] = None
    cumulative: bool = False
    once_only: bool = False
    no_excursion: bool = False
    freeze_sensitive: bool = False
    presentation_mismatch_risk: bool = False
    cumulative_above_label: bool = False  # "72h above 8°C" — 8 is threshold, not cap
    notes: list[str] = None

    def __post_init__(self) -> None:
        """Derive structured fields from permitted_excursion_text after init."""
        if self.notes is None:
            self.notes = []


def _parse_allowance(text: str) -> dict[str, Any]:
    """Parse free-text permitted-excursion language into structured allowance fields."""
    t = (text or "").strip()
    out: dict[str, Any] = {
        "no_excursion": False,
        "cumulative": False,
        "once_only": False,
        "max_temp_c": None,
        "max_duration_hours": None,
        "refer_qa": False,
        "freeze_sensitive": "do not freeze" in t.lower(),
        "cumulative_above_label": False,
    }
    tl = t.lower()
    if not t:
        return out
    if "refer qa" in tl:
        out["refer_qa"] = True
        return out
    if "no excursion" in tl:
        out["no_excursion"] = True
        return out
    if "cumulative" in tl:
        out["cumulative"] = True
    if "once" in tl:
        out["once_only"] = True
    # ≤ 6 h to 15 °C
    m = re.search(
        r"(?:≤|<=)?\s*(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(?:to|below|at|above)?\s*(\d+(?:\.\d+)?)\s*°?\s*c",
        tl,
    )
    if m:
        out["max_duration_hours"] = float(m.group(1))
        out["max_temp_c"] = float(m.group(2))
    m2 = re.search(
        r"cumulative\s+(\d+)\s*h(?:ours?)?\s*above\s*(\d+(?:\.\d+)?)",
        tl,
    )
    if m2:
        out["max_duration_hours"] = float(m2.group(1))
        out["max_temp_c"] = float(m2.group(2))  # labelled threshold, not absolute cap
        out["cumulative"] = True
        out["cumulative_above_label"] = True
    m3 = re.search(
        r"excursions?\s+to\s+(\d+(?:\.\d+)?)\s*c?\s*up\s+to\s+(\d+)\s*days?",
        tl,
    )
    if m3:
        out["max_temp_c"] = float(m3.group(1))
        out["max_duration_hours"] = float(m3.group(2)) * 24
        out["cumulative"] = True
    m4 = re.search(
        r"single excursion\s*≤\s*(\d+)\s*h\s*to\s*(\d+)",
        tl,
    )
    if m4:
        out["max_duration_hours"] = float(m4.group(1))
        out["max_temp_c"] = float(m4.group(2))
        out["once_only"] = True
    return out


class StabilityResolver:
    """Resolves stability study / master permitted-excursion text for a product."""
    def __init__(self, pack: DataPack) -> None:
        """Bind the resolver to a loaded DataPack."""
        self.pack = pack
        self.by_ref = {str(s.get("study_ref")): s for s in pack.stability if s.get("study_ref")}

    def resolve(self, product: ResolvedProduct) -> StabilityPosition:
        """Return the stability position for a resolved product (master preferred on mismatch)."""
        notes: list[str] = []
        study_ref = product.stability_study_ref
        master_text = product.permitted_excursion_text
        study = self.by_ref.get(str(study_ref)) if study_ref else None

        if study_ref and not study:
            notes.append(
                f"product master cites {study_ref} but it is absent from 06_Stability_Index "
                "(index covers ~60% of repository — pack README)"
            )

        presentation_risk = False
        if study and product.brand:
            study_prod = str(study.get("product_text_as_written") or "").lower()
            # vial vs pen mismatch — the EXC-110497 failure mode
            brand_l = product.brand.lower()
            if ("vial" in study_prod and "pen" in brand_l) or (
                "pen" in study_prod and "vial" in brand_l
            ):
                presentation_risk = True
                notes.append(
                    f"presentation mismatch risk: master brand {product.brand!r} vs study "
                    f"{study.get('product_text_as_written')!r}"
                )
            if product.presentation_hint == "pen" and "vial" in study_prod:
                presentation_risk = True
            if product.presentation_hint == "vial" and "pen" in study_prod:
                presentation_risk = True

        study_text = None
        readable = True
        if study:
            readable = str(study.get("readable") or "Y").upper().startswith("Y") or str(
                study.get("readable")
            ).startswith("Partial")
            if str(study.get("readable") or "").startswith("N"):
                readable = False
                notes.append("stability study marked unreadable (scan of scan)")
            study_text = study.get("permitted_excursion_text") or ""
            if not study_text:
                notes.append(
                    "stability study has blank permitted_excursion_text "
                    "(long-term/accelerated studies do not answer excursion question — README)"
                )

        # Prefer study excursion text when present, readable, and presentation-aligned.
        # Pack trap (EXC-107133 / T-KAVERI): master brand is SoloJet (pen) but cited
        # STB-3584 is indexed as vial — use master permitted text instead of the
        # mismatched study (EXC-110497 failure mode).
        if presentation_risk and master_text and str(master_text).strip():
            notes.append(
                "cited study presentation conflicts with brand; preferring product-master "
                "permitted_excursion_text over mismatched study row"
            )
            parsed = _parse_allowance(str(master_text))
            source = "product_master_over_mismatched_study"
            text = master_text
            if parsed.get("refer_qa"):
                notes.append("master says 'Refer QA' — not a usable allowance (override EXC-110574)")
        elif study_text and readable:
            parsed = _parse_allowance(str(study_text))
            source = "stability_index"
            text = study_text
            if master_text and str(master_text).strip() and str(master_text).strip() != str(study_text).strip():
                notes.append(
                    f"master permitted_excursion_text differs from study: master={master_text!r}"
                )
                source = "both"
        elif master_text:
            parsed = _parse_allowance(str(master_text))
            source = "product_master"
            text = master_text
            if parsed.get("refer_qa"):
                notes.append("master says 'Refer QA' — not a usable allowance (override EXC-110574)")
        else:
            return StabilityPosition(
                study_ref=study_ref,
                permitted_text=None,
                readable=readable,
                source="none",
                presentation_mismatch_risk=presentation_risk,
                notes=notes + ["no permitted excursion text available"],
            )

        return StabilityPosition(
            study_ref=str(study_ref) if study_ref else None,
            permitted_text=str(text) if text else None,
            readable=readable,
            source=source,
            max_temp_c=parsed.get("max_temp_c"),
            max_duration_hours=parsed.get("max_duration_hours"),
            cumulative=bool(parsed.get("cumulative")),
            once_only=bool(parsed.get("once_only")),
            no_excursion=bool(parsed.get("no_excursion")),
            freeze_sensitive=bool(parsed.get("freeze_sensitive")),
            presentation_mismatch_risk=presentation_risk,
            cumulative_above_label=bool(parsed.get("cumulative_above_label")),
            notes=notes,
        )


# ====REGULATORY====
"""Regulatory notification windows — measured from alert_ts, not disposition.

Source of truth for windows: tab 13_Volume_And_Cost row on 'Regulatory notification
windows in the book', plus tab 12 tenant-specific notes (Campos = 5 calendar days).
The pack is silent on a per-tenant table; we take an explicit position below.
"""


from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional


# Position taken (brief §Kavitha + pack tab 13 row 22 + tab 12 T-CAMPOS):
# - EU tenants default 72h where market requires notification (we mark reportable
#   when historical row says Y, else compute window for tenant region).
# - Brazil (T-CAMPOS): 5 calendar days.
# - US: next-business-day programme is one state — without a state field we use
#   24h as the conservative operational SLA for reportable US cases.
# - India: 15 days for notifiable products only.
DEFAULT_WINDOWS_HOURS = {
    "T-AURA": 72,
    "T-NORDIA": 72,
    "T-CAMPOS": 5 * 24,
    "T-PINNACLE": 24,
    "T-MERIDIAN": 24,
    "T-VIRENT": 15 * 24,
    "T-SAHYADRI": 15 * 24,
    "T-KAVERI": 15 * 24,
}

REGION_DEFAULTS = {
    "EMEA": 72,
    "AMER": 24,
    "APAC": 15 * 24,
    "LATAM": 5 * 24,
}


@dataclass
class RegulatoryClock:
    """Regulatory notification window and deadline derived from alert time and tenant rules."""
    reportable: bool
    window_hours: Optional[float]
    deadline_utc: Optional[datetime]
    basis: str
    hours_remaining_at_eval: Optional[float] = None


def regulatory_clock(
    tenant_code: str,
    alert_ts: Optional[datetime],
    tenant_row: Optional[dict[str, Any]] = None,
    historically_reportable: Any = None,
    historical_window_hours: Any = None,
    eval_ts: Optional[datetime] = None,
) -> RegulatoryClock:
    """Compute the notification deadline.

    Prefer the pack's historical reg_window_hours when present (ground truth for
    that case). Otherwise apply our tenant/region position.
    """
    reportable = str(historically_reportable or "").upper() == "Y"
    window = None
    basis = ""
    if historical_window_hours not in (None, ""):
        try:
            window = float(historical_window_hours)
            basis = "pack.reg_window_hours"
        except (TypeError, ValueError):
            window = None

    if window is None:
        if tenant_code in DEFAULT_WINDOWS_HOURS:
            window = float(DEFAULT_WINDOWS_HOURS[tenant_code])
            basis = f"tenant_default[{tenant_code}]"
        elif tenant_row and tenant_row.get("region") in REGION_DEFAULTS:
            window = float(REGION_DEFAULTS[tenant_row["region"]])
            basis = f"region_default[{tenant_row['region']}]"
        else:
            window = 72.0
            basis = "fallback_72h"

    # If not marked reportable historically and no historical window, keep window
    # for operational awareness but flag reportable=False unless tenant is Campos
    # (always track) — disposition path still uses it when reportable.
    deadline = None
    remaining = None
    if alert_ts is not None and window is not None:
        deadline = alert_ts + timedelta(hours=window)
        if eval_ts is None:
            eval_ts = alert_ts
        remaining = (deadline - eval_ts).total_seconds() / 3600.0

    return RegulatoryClock(
        reportable=reportable,
        window_hours=window if reportable or historical_window_hours not in (None, "") else window,
        deadline_utc=deadline if reportable or historical_window_hours not in (None, "") else deadline,
        basis=basis,
        hours_remaining_at_eval=remaining,
    )


# ====ENGINE====
"""Deterministic as-of adjudication engine.

This is the component that would keep me up at night: given an excursion alert,
assemble the evidence that was true on the excursion date and recommend an
outcome + regulatory deadline without inventing citations.

LLM drafting of justification text is deliberately out of scope here (see
docs/01-where-you-land.md). Closures of clear non-actionable alerts may be
AUTO_CLOSE; actionable dispositions that change product fate require human sign-off
per Dr Rao's board condition — the engine still emits a recommendation and a
structured evidence basis.
"""


from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


# ThermaTrace bulletin TT-CB-114 (INC-2506 / pack 14): firmware TT-2.14.3
# under-reported by as much as 1.8 °C.
BULLETIN_FW = "TT-2.14.3"
BULLETIN_BIAS_C = 1.8

AUTO_CLOSE = "AUTO_CLOSE"
RELEASE = "RELEASE"
RELEASE_WITH_NOTE = "RELEASE_WITH_NOTE"
QUARANTINE_PENDING_LAB = "QUARANTINE_PENDING_LAB"
DESTROY = "DESTROY"
RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"
REWORK_RELABEL = "REWORK_RELABEL"
ESCALATE = "ESCALATED_TO_SENIOR_QA"

ACTIONABLE_DISPOSITIONS = {
    RELEASE,
    RELEASE_WITH_NOTE,
    QUARANTINE_PENDING_LAB,
    DESTROY,
    RETURN_TO_ORIGIN,
    REWORK_RELABEL,
    ESCALATE,
}


@dataclass
class AdjudicationResult:
    """Structured adjudication output: disposition, confidence, rationale, and evidence outline."""
    event_id: str
    tenant_code: str
    recommendation: str
    requires_human_signature: bool
    confidence: float
    triage_label: str
    rationale: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    product_match_method: Optional[str] = None
    product_sku: Optional[str] = None
    product_brand: Optional[str] = None
    stability_study_ref: Optional[str] = None
    sop_doc_id: Optional[str] = None
    sop_revision: Optional[str] = None
    sop_overlap_conflict: bool = False
    carrier_contract_id: Optional[str] = None
    carrier_has_cold_chain_clause: Optional[bool] = None
    corrected_max_temp_c: Optional[float] = None
    bulletin_applied: bool = False
    regulator_reportable: bool = False
    reg_window_hours: Optional[float] = None
    reg_deadline_utc: Optional[str] = None
    historical_recommendation: Optional[str] = None
    historical_final_disposition: Optional[str] = None
    agrees_with_historical_final: Optional[bool] = None
    agrees_with_historical_engine: Optional[bool] = None

    def to_row(self) -> dict[str, Any]:
        """Flatten the result into a CSV/JSON-friendly dict row."""
        d = asdict(self)
        d["rationale"] = " | ".join(self.rationale)
        d["evidence"] = str(self.evidence)
        return d


class AdjudicationEngine:
    """Deterministic as-of adjudication engine over a DataPack."""
    def __init__(self, pack: DataPack) -> None:
        """Bind identity/stability resolvers to the pack."""
        self.pack = pack
        self.identity = IdentityResolver(pack)
        self.stability = StabilityResolver(pack)
        self.tenants = {t["tenant_code"]: t for t in pack.tenants}

    def adjudicate(self, event: dict[str, Any]) -> AdjudicationResult:
        """Adjudicate one excursion event dict into an AdjudicationResult."""
        event_id = str(event.get("event_id"))
        tenant = str(event.get("tenant_code") or "")
        rationale: list[str] = []
        evidence: dict[str, Any] = {"event_id": event_id, "tenant_code": tenant}

        alert_ts: Optional[datetime] = event.get("_alert_ts")
        as_of = (event.get("_excursion_start") or alert_ts or datetime.utcnow()).date()

        # --- sensor bulletin correction ---
        max_temp = _f(event.get("max_temp_c"))
        min_temp = _f(event.get("min_temp_c"))
        duration_min = _f(event.get("duration_min")) or 0.0
        bulletin = str(event.get("logger_fw") or "") == BULLETIN_FW
        corrected_max = max_temp
        if bulletin and max_temp is not None:
            corrected_max = max_temp + BULLETIN_BIAS_C
            rationale.append(
                f"Applied TT-CB-114: firmware {BULLETIN_FW} under-reports ≤{BULLETIN_BIAS_C}°C; "
                f"corrected max {max_temp}→{corrected_max:.1f}°C"
            )
        evidence["temps"] = {
            "min": min_temp,
            "max_reported": max_temp,
            "max_corrected": corrected_max,
            "duration_min": duration_min,
            "bulletin_tt_cb_114": bulletin,
        }

        # --- identity ---
        product = self.identity.resolve_product(tenant, event.get("product_ref_as_received"))
        evidence["product"] = {
            "ref_as_received": event.get("product_ref_as_received"),
            "match_method": product.match_method,
            "confidence": product.confidence,
            "sku": product.internal_sku,
            "brand": product.brand,
            "gtin": product.gtin,
            "stability_study_ref": product.stability_study_ref,
            "unresolved_reason": product.unresolved_reason,
        }
        if product.confidence < 0.5:
            rationale.append(
                f"Product identity weak ({product.match_method}): {product.unresolved_reason}"
            )

        # --- labelled range ---
        spec_text = product.storage_spec_text or event.get("spec_text_as_received")
        low, high = parse_storage_range(spec_text)
        evidence["labelled_range"] = {"text": spec_text, "low_c": low, "high_c": high}

        # --- stability as cited ---
        stab = self.stability.resolve(product)
        evidence["stability"] = {
            "study_ref": stab.study_ref,
            "permitted_text": stab.permitted_text,
            "source": stab.source,
            "readable": stab.readable,
            "notes": stab.notes,
            "presentation_mismatch_risk": stab.presentation_mismatch_risk,
        }
        rationale.extend(stab.notes)

        # --- SOP as-at excursion date ---
        sop_hit = sop_in_force(
            self.pack.sops, tenant, "Temperature Excursion Management", as_of
        )
        sop_overlap = False
        sop_doc = sop_rev = None
        if sop_hit:
            sop_doc = sop_hit.record.get("doc_id")
            sop_rev = sop_hit.record.get("revision")
            sop_overlap = sop_hit.overlap_conflict
            evidence["sop"] = {
                "doc_id": sop_doc,
                "revision": sop_rev,
                "effective_from": str(sop_hit.record.get("_effective_from")),
                "effective_to": str(sop_hit.record.get("_effective_to")),
                "acceptance_limits_location": sop_hit.record.get("acceptance_limits_location"),
                "overlap_conflict": sop_overlap,
                "competing_revisions": [c.get("revision") for c in sop_hit.competing],
            }
            if sop_overlap:
                rationale.append(
                    f"SOP overlap: {len(sop_hit.competing)} revisions of {sop_doc} "
                    f"effective on {as_of}; selected {sop_rev} (highest rev). "
                    "Human must confirm (override EXC-110490 pattern)."
                )
        else:
            evidence["sop"] = None
            rationale.append(f"No Temperature Excursion Management SOP in force for {tenant} on {as_of}")

        # --- carrier contract as-at ---
        carrier, carrier_err = self.identity.resolve_carrier_contract(
            event.get("carrier_ref_as_received"), as_of
        )
        has_cc = None
        carrier_id = None
        if carrier:
            carrier_id = carrier.get("contract_id")
            clause = str(carrier.get("cold_chain_clause") or "")
            has_cc = "none" not in clause.lower() and clause.strip() not in {"", "—", "-"}
            evidence["carrier"] = {
                "contract_id": carrier_id,
                "legal_entity": carrier.get("counterparty_legal_entity"),
                "cold_chain_clause": clause,
                "claim_window_days": carrier.get("claim_window_days"),
            }
            if not has_cc:
                rationale.append(
                    f"Carrier contract {carrier_id} has no cold-chain schedule "
                    "(Tapti/Ganga pattern) — liability/custody weak; does not alone "
                    "change product disposition"
                )
        else:
            evidence["carrier"] = {"error": carrier_err}
            rationale.append(carrier_err or "carrier unresolved")

        # --- regulatory clock ---
        clock = regulatory_clock(
            tenant_code=tenant,
            alert_ts=alert_ts,
            tenant_row=self.tenants.get(tenant),
            historically_reportable=event.get("regulator_reportable"),
            historical_window_hours=event.get("reg_window_hours"),
            eval_ts=alert_ts,
        )
        evidence["regulatory"] = {
            "reportable": clock.reportable,
            "window_hours": clock.window_hours,
            "deadline_utc": clock.deadline_utc.isoformat(sep=" ") if clock.deadline_utc else None,
            "basis": clock.basis,
        }

        # --- triage / recommendation ---
        recommendation, triage, conf, extra = self._decide(
            event=event,
            product=product,
            stab=stab,
            low=low,
            high=high,
            corrected_max=corrected_max,
            min_temp=min_temp,
            duration_min=duration_min,
            sop_overlap=sop_overlap,
            has_cold_chain_clause=has_cc,
        )
        rationale.extend(extra)

        requires_human = recommendation != AUTO_CLOSE
        # Dr Rao: automation on closures only. Even high-confidence RELEASE requires sign-off.
        if recommendation in ACTIONABLE_DISPOSITIONS:
            requires_human = True

        hist_eng = event.get("rules_engine_recommendation")
        hist_final = event.get("final_disposition")
        agrees_final = None
        agrees_eng = None
        if hist_final:
            agrees_final = recommendation == hist_final
        if hist_eng:
            agrees_eng = recommendation == hist_eng

        return AdjudicationResult(
            event_id=event_id,
            tenant_code=tenant,
            recommendation=recommendation,
            requires_human_signature=requires_human,
            confidence=conf,
            triage_label=triage,
            rationale=rationale,
            evidence=evidence,
            product_match_method=product.match_method,
            product_sku=product.internal_sku,
            product_brand=product.brand,
            stability_study_ref=stab.study_ref,
            sop_doc_id=str(sop_doc) if sop_doc else None,
            sop_revision=str(sop_rev) if sop_rev else None,
            sop_overlap_conflict=sop_overlap,
            carrier_contract_id=str(carrier_id) if carrier_id else None,
            carrier_has_cold_chain_clause=has_cc,
            corrected_max_temp_c=corrected_max,
            bulletin_applied=bulletin,
            regulator_reportable=clock.reportable,
            reg_window_hours=clock.window_hours,
            reg_deadline_utc=clock.deadline_utc.isoformat(sep=" ") if clock.deadline_utc else None,
            historical_recommendation=str(hist_eng) if hist_eng else None,
            historical_final_disposition=str(hist_final) if hist_final else None,
            agrees_with_historical_final=agrees_final,
            agrees_with_historical_engine=agrees_eng,
        )

    def _decide(
        self,
        event: dict[str, Any],
        product: ResolvedProduct,
        stab: StabilityPosition,
        low: Optional[float],
        high: Optional[float],
        corrected_max: Optional[float],
        min_temp: Optional[float],
        duration_min: float,
        sop_overlap: bool,
        has_cold_chain_clause: Optional[bool],
    ) -> tuple[str, str, float, list[str]]:
        """Apply disposition rules given resolved product, stability, temps, and SOP overlap."""
        notes: list[str] = []
        duration_h = duration_min / 60.0
        gap = _f(event.get("gateway_gap_min")) or 0.0
        interpolated = str(event.get("interpolated") or "").upper() == "Y"
        dock = str(event.get("dock_door_open_flag") or "").upper() == "Y"
        prior = int(event.get("prior_excursions_lane_90d") or 0)
        triage_hist = str(event.get("triage_outcome") or "")

        # Cheap non-actionable triages first — blank product_ref is common on BMS
        # facility storms (INC-2502) and must not force escalation.
        if "facility equipment event" in triage_hist.lower():
            notes.append("Triage indicates facility equipment event with no product loaded")
            return AUTO_CLOSE, "NON_ACTIONABLE — facility equipment event, no product loaded", 0.85, notes

        if "duplicate" in triage_hist.lower():
            notes.append("Triage indicates duplicate of earlier alert")
            return AUTO_CLOSE, "NON_ACTIONABLE — duplicate of earlier alert", 0.8, notes

        # Gateway gap overlapping excursion with interpolated readings
        if gap > 0 and interpolated and gap >= max(duration_min * 0.5, 30):
            notes.append(
                f"Gateway gap {gap} min with interpolated readings — insufficient evidence of excursion"
            )
            return (
                RELEASE_WITH_NOTE if _out_of_range(corrected_max, min_temp, low, high) else AUTO_CLOSE,
                "NON_ACTIONABLE — sensor artefact (gap)",
                0.7,
                notes,
            )

        # Hard escalate conditions — cannot safely auto-decide product fate
        if product.confidence < 0.5:
            notes.append("Escalate: unresolved/ambiguous product identity")
            return ESCALATE, "ACTIONABLE — identity unresolved", 0.35, notes

        if stab.presentation_mismatch_risk and stab.source != "product_master_over_mismatched_study":
            notes.append("Escalate: stability study may be wrong presentation (vial vs pen)")
            return ESCALATE, "ACTIONABLE — presentation mismatch risk", 0.4, notes
        if stab.presentation_mismatch_risk:
            notes.append(
                "Presentation mismatch on cited study — using master allowance with reduced confidence"
            )

        # SOP overlap: brief EXC-107133 — overlapping revs did NOT change the
        # outcome when stability was decisive. Flag + require human (already true
        # for actionable) but do not hard-stop before allowance arithmetic.
        if sop_overlap:
            notes.append(
                "SOP revision overlap on excursion date — human must confirm which "
                "acceptance limit governed; proceeding with stability arithmetic"
            )

        if stab.notes and any("Refer QA" in n or "'Refer QA'" in n or "refer qa" in n.lower() for n in stab.notes):
            notes.append("Escalate: permitted allowance is 'Refer QA'")
            return ESCALATE, "ACTIONABLE — allowance refer QA", 0.4, notes

        if not stab.readable and stab.study_ref:
            notes.append("Escalate: cited stability study unreadable")
            return QUARANTINE_PENDING_LAB, "ACTIONABLE — unreadable stability", 0.5, notes

        if "sensor artefact" in triage_hist.lower() and gap == 0:
            # Only auto-close sensor artefact when no conflicting severity
            if high is not None and corrected_max is not None and corrected_max <= high + 0.5:
                notes.append("Sensor artefact triage; corrected temp near labelled range")
                return AUTO_CLOSE, "NON_ACTIONABLE — sensor artefact", 0.75, notes

        if dock and duration_min <= 20 and high is not None and corrected_max is not None:
            if corrected_max <= high + 5:
                notes.append("Short dock-door ambient exposure pattern")
                # Still verify door timing would be needed in prod; conservative note
                if "dock door" in triage_hist.lower():
                    return AUTO_CLOSE, "NON_ACTIONABLE — dock door / ambient exposure", 0.7, notes

        out_of_range = _out_of_range(corrected_max, min_temp, low, high)
        if not out_of_range:
            notes.append("Corrected temperatures within labelled storage range")
            return AUTO_CLOSE, "NON_ACTIONABLE — within labelled range", 0.9, notes

        # Freeze damage on cold-chain (not ultra-cold) product
        if (
            high is not None
            and high <= 8
            and low is not None
            and low >= 0
            and min_temp is not None
            and min_temp < 0
        ):
            notes.append(
                f"Below 0°C on 2–8°C labelled product (min={min_temp}) — freeze damage risk "
                "(override EXC-110483 pattern)"
            )
            return DESTROY, "ACTIONABLE — freeze excursion", 0.75, notes

        # Ultra-cold / LN2: short documented top-up vs real excursion
        if low is not None and low <= -60:
            if duration_min <= 5:
                notes.append("Ultra-cold: ≤5 min excursion — possible dry-ice replenishment")
                return RELEASE_WITH_NOTE, "ACTIONABLE — ultra-cold short open", 0.55, notes
            if stab.no_excursion or (stab.max_duration_hours and duration_h > stab.max_duration_hours):
                notes.append("Ultra-cold beyond permitted hold")
                return DESTROY, "ACTIONABLE — ultra-cold breach", 0.7, notes

        # Stability allowance
        if stab.no_excursion:
            notes.append(f"Stability/master: no excursion permitted ({stab.permitted_text})")
            if duration_h <= 0.25 and high is not None and corrected_max is not None and corrected_max <= high + 2:
                return QUARANTINE_PENDING_LAB, "ACTIONABLE — brief breach, no-excursion product", 0.6, notes
            return DESTROY, "ACTIONABLE — no excursion permitted", 0.7, notes

        if stab.max_duration_hours is not None and (
            stab.max_temp_c is not None or stab.cumulative_above_label
        ):
            within_dur = duration_h <= stab.max_duration_hours + 1e-9
            if stab.cumulative_above_label:
                # "72 h above 8 °C" — threshold is the labelled edge; duration above
                # it is the budget. Absolute severity still gated loosely (e.g. >30C).
                threshold = stab.max_temp_c if stab.max_temp_c is not None else high
                within_temp = True
                if corrected_max is not None and corrected_max > 30:
                    within_temp = False
                notes.append(
                    f"Cumulative-above-label check: {duration_h:.2f}h above ~{threshold}°C "
                    f"vs budget ≤{stab.max_duration_hours}h; peak {corrected_max}°C "
                    f"(source={stab.source})"
                )
            else:
                within_temp = corrected_max is not None and corrected_max <= stab.max_temp_c + 1e-6
                notes.append(
                    f"Allowance check: duration {duration_h:.2f}h vs ≤{stab.max_duration_hours}h; "
                    f"max {corrected_max}°C vs ≤{stab.max_temp_c}°C "
                    f"(source={stab.source})"
                )
            if within_temp and within_dur:
                if stab.cumulative or stab.cumulative_above_label:
                    notes.append(
                        "Within single-event allowance but exposure is cumulative across shelf life "
                        "— release with batch note"
                    )
                    conf = 0.8 if stab.presentation_mismatch_risk else 0.85
                    return (
                        RELEASE_WITH_NOTE,
                        "ACTIONABLE — within allowance, cumulative note required",
                        conf,
                        notes,
                    )
                notes.append("Within permitted excursion allowance")
                return (
                    AUTO_CLOSE,
                    "NON_ACTIONABLE — within permitted excursion allowance",
                    0.88,
                    notes,
                )
            # Exceeded allowance
            if (
                not stab.cumulative_above_label
                and corrected_max is not None
                and stab.max_temp_c is not None
                and corrected_max > stab.max_temp_c + 5
            ):
                notes.append("Exceeded allowance temperature by >5°C")
                return DESTROY, "ACTIONABLE — severe temperature breach", 0.7, notes
            notes.append("Exceeded permitted allowance — quarantine pending lab")
            return QUARANTINE_PENDING_LAB, "ACTIONABLE — allowance exceeded", 0.65, notes

        # No parseable allowance but out of range
        notes.append("Out of labelled range with no parseable excursion allowance")
        if duration_h <= 0.5 and high is not None and corrected_max is not None and corrected_max <= high + 3:
            return RELEASE_WITH_NOTE, "ACTIONABLE — brief mild excursion", 0.55, notes
        if prior >= 3:
            notes.append(f"Lane has {prior} prior excursions in 90d — cumulative trust concern")
            return QUARANTINE_PENDING_LAB, "ACTIONABLE — repeat lane pattern", 0.55, notes
        return QUARANTINE_PENDING_LAB, "ACTIONABLE — excursion confirmed", 0.5, notes


def _f(v: Any) -> Optional[float]:
    """Coerce a value to float, or None if missing/invalid."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _out_of_range(
    max_t: Optional[float],
    min_t: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> bool:
    """True if min/max temps fall outside the labelled [low, high] storage range."""
    if high is not None and max_t is not None and max_t > high + 1e-9:
        return True
    if low is not None and min_t is not None and min_t < low - 1e-9:
        return True
    return False


# ====EVIDENCE====
"""Immutable, append-only, hash-chained evidence bundles.

Each recommendation writes a content-addressed JSON document. Bundles for a
tenant form a hash chain (prev_hash). Tampering breaks verify_chain().
Tenant isolation: load/get require tenant_code and refuse cross-tenant reads.
"""


import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4



def _utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of a canonical JSON serialization of payload."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class EvidenceStore:
    """Append-only, hash-chained, per-tenant evidence bundle store with Cl.22 isolation."""
    def __init__(
        self,
        root: Path | str,
        db: BitemporalStore,
        *,
        retention_years: int = 7,
    ) -> None:
        """Bind filesystem root and bitemporal DB index; create root directory."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.retention_years = retention_years

    def _tenant_dir(self, tenant_code: str) -> Path:
        """Return (and create) the per-tenant evidence directory."""
        d = self.root / tenant_code
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _last_hash(self, tenant_code: str) -> Optional[str]:
        """Return the latest content hash in the tenant chain, or None if empty."""
        chain = self.db.chain_for_tenant(tenant_code)
        return chain[-1]["content_hash"] if chain else None

    def write_bundle(
        self,
        *,
        tenant_code: str,
        event_id: str,
        recommendation: dict[str, Any],
        inputs: dict[str, Any],
        reasoning_steps: list[str],
        rule_pack_version: str,
        ref_snapshot_id: str,
        code_version: str,
        case_id: Optional[str] = None,
        reviewer_signoff: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Write a new evidence bundle, link prev_hash, and index metadata."""
        created = _utcnow()
        retention_until = created + timedelta(days=365 * self.retention_years + 2)  # leap cushion
        prev = self._last_hash(tenant_code)
        # Content-addressed core (hash excludes bundle_id/path/prev to allow chain link)
        core = {
            "tenant_code": tenant_code,
            "event_id": event_id,
            "case_id": case_id,
            "created_at": created.isoformat(sep=" "),
            "retention_until": retention_until.isoformat(sep=" "),
            "retention_years": self.retention_years,
            "rule_pack_version": rule_pack_version,
            "ref_snapshot_id": ref_snapshot_id,
            "code_version": code_version,
            "inputs": inputs,
            "recommendation": recommendation,
            "reasoning_steps": reasoning_steps,
            "reviewer_signoff": reviewer_signoff
            or {"status": "UNSIGNED", "signed_by": None, "signed_at": None},
        }
        content_hash = canonical_hash(core)
        bundle_id = f"EVB-{content_hash[:16]}"
        document = {
            **core,
            "bundle_id": bundle_id,
            "content_hash": content_hash,
            "prev_hash": prev,
            "schema": "kestrel.evidence.v1",
        }
        path = self._tenant_dir(tenant_code) / f"{bundle_id}.json"
        path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
        meta = {
            "bundle_id": bundle_id,
            "tenant_code": tenant_code,
            "event_id": event_id,
            "case_id": case_id,
            "content_hash": content_hash,
            "prev_hash": prev,
            "path": str(path),
            "created_at": created.isoformat(sep=" "),
            "retention_until": retention_until.isoformat(sep=" "),
            "rule_pack_version": rule_pack_version,
            "ref_snapshot_id": ref_snapshot_id,
            "code_version": code_version,
        }
        self.db.index_evidence(meta)
        return document

    def get(
        self,
        bundle_id: str,
        *,
        tenant_code: str,
        measure: bool = False,
    ) -> dict[str, Any]:
        """Retrieve full basis for a disposition. Enforces tenant isolation."""
        t0 = time.perf_counter()
        meta = self.db.get_evidence_meta(bundle_id, tenant_code=tenant_code)
        if not meta:
            # Distinguish missing vs cross-tenant
            any_meta = self.db.get_evidence_meta(bundle_id, tenant_code=None)
            if any_meta and any_meta["tenant_code"] != tenant_code:
                raise PermissionError(
                    f"tenant isolation: bundle {bundle_id} belongs to "
                    f"{any_meta['tenant_code']}, not {tenant_code} (Meridian Cl.22)"
                )
            raise FileNotFoundError(f"evidence bundle not found: {bundle_id}")
        path = Path(meta["path"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("tenant_code") != tenant_code:
            raise PermissionError("tenant isolation violation on disk document")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if measure:
            doc["_retrieval_latency_ms"] = elapsed_ms
        return doc

    def verify_document(self, doc: dict[str, Any]) -> bool:
        """Recompute content hash and verify it matches the document metadata."""
        core = {
            k: doc[k]
            for k in (
                "tenant_code",
                "event_id",
                "case_id",
                "created_at",
                "retention_until",
                "retention_years",
                "rule_pack_version",
                "ref_snapshot_id",
                "code_version",
                "inputs",
                "recommendation",
                "reasoning_steps",
                "reviewer_signoff",
            )
            if k in doc
        }
        return canonical_hash(core) == doc.get("content_hash")

    def verify_chain(self, tenant_code: str) -> dict[str, Any]:
        """Walk the tenant hash chain and report tamper/length errors."""
        chain = self.db.chain_for_tenant(tenant_code)
        errors: list[str] = []
        prev: Optional[str] = None
        for i, meta in enumerate(chain):
            doc = json.loads(Path(meta["path"]).read_text(encoding="utf-8"))
            if not self.verify_document(doc):
                errors.append(f"{meta['bundle_id']}: content hash mismatch (tamper)")
            expected_prev = prev
            if doc.get("prev_hash") != expected_prev:
                errors.append(
                    f"{meta['bundle_id']}: chain break at index {i}: "
                    f"prev_hash={doc.get('prev_hash')} expected={expected_prev}"
                )
            prev = doc.get("content_hash")
        return {
            "tenant_code": tenant_code,
            "length": len(chain),
            "ok": not errors,
            "errors": errors,
        }

    def produce_full_basis(
        self, event_id: str, tenant_code: str
    ) -> dict[str, Any]:
        """Board commitment 3: full basis on request — measure latency."""
        t0 = time.perf_counter()
        metas = self.db.evidence_for_event(event_id, tenant_code)
        if not metas:
            raise FileNotFoundError(f"no evidence for {event_id} under {tenant_code}")
        # Latest bundle
        meta = metas[-1]
        doc = self.get(meta["bundle_id"], tenant_code=tenant_code, measure=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "event_id": event_id,
            "tenant_code": tenant_code,
            "bundle": doc,
            "retrieval_latency_ms": elapsed_ms,
            "within_one_hour": elapsed_ms < 3_600_000,
            "retention_until": meta["retention_until"],
            "versions": {
                "rule_pack_version": meta["rule_pack_version"],
                "ref_snapshot_id": meta["ref_snapshot_id"],
                "code_version": meta["code_version"],
            },
        }


# ====LIFECYCLE====
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4



ALLOWED: dict[CaseState, set[CaseState]] = {
    CaseState.NEW: {
        CaseState.TRIAGED_NON_ACTIONABLE,
        CaseState.PENDING_EVIDENCE,
        CaseState.RECOMMENDED,
        CaseState.AWAITING_REVIEWER,
    },
    CaseState.TRIAGED_NON_ACTIONABLE: {CaseState.CLOSED_AUTO, CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_EVIDENCE: {CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER},
    CaseState.RECOMMENDED: {
        CaseState.AWAITING_REVIEWER,
        CaseState.RETURNED_FOR_DATA,
        CaseState.PENDING_LAB,
        CaseState.PENDING_SECOND_SIGN,
        CaseState.CLOSED_SIGNED,
        CaseState.CLOSED_AUTO,
    },
    CaseState.AWAITING_REVIEWER: {
        CaseState.RETURNED_FOR_DATA,
        CaseState.PENDING_LAB,
        CaseState.PENDING_SECOND_SIGN,
        CaseState.CLOSED_SIGNED,
    },
    CaseState.RETURNED_FOR_DATA: {CaseState.PENDING_EVIDENCE, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_LAB: {CaseState.CLOSED_SIGNED, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_SECOND_SIGN: {CaseState.CLOSED_SIGNED},
    CaseState.CLOSED_AUTO: {CaseState.REOPENED},
    CaseState.CLOSED_SIGNED: {CaseState.REOPENED},
    CaseState.REOPENED: {CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER, CaseState.PENDING_EVIDENCE},
}


def _utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CaseLifecycle:
    """Case state machine with sign, reopen, and regulatory-deadline priority queue."""
    def __init__(self, store: BitemporalStore) -> None:
        """Bind lifecycle operations to a BitemporalStore."""
        self.store = store

    def create(
        self,
        *,
        event_id: str,
        tenant_code: str,
        reg_deadline_utc: Optional[datetime],
        regulator_reportable: bool,
        recommendation: Optional[Disposition] = None,
        evidence_bundle_id: Optional[str] = None,
        reopened_from: Optional[str] = None,
        reopen_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a case from an adjudication recommendation and persist it."""
        now = _utcnow()
        # Priority: reportable with nearer deadline sorts first via store queue
        priority = 100.0 if regulator_reportable else 10.0
        if recommendation == Disposition.AUTO_CLOSE:
            state = CaseState.TRIAGED_NON_ACTIONABLE
        elif recommendation in ACTIONABLE:
            state = CaseState.AWAITING_REVIEWER
        else:
            state = CaseState.NEW
        if reopened_from:
            state = CaseState.REOPENED
        case = {
            "case_id": f"CASE-{uuid4().hex[:12]}",
            "event_id": event_id,
            "tenant_code": tenant_code,
            "state": state.value,
            "recommendation": recommendation.value if recommendation else None,
            "final_disposition": None,
            "evidence_bundle_id": evidence_bundle_id,
            "reg_deadline_utc": reg_deadline_utc.isoformat(sep=" ") if reg_deadline_utc else None,
            "regulator_reportable": regulator_reportable,
            "priority_score": priority,
            "reopened_from_case_id": reopened_from,
            "reopen_reason": reopen_reason,
            "created_at": now.isoformat(sep=" "),
            "updated_at": now.isoformat(sep=" "),
            "signed_by": None,
            "signed_at": None,
        }
        self.store.save_case(case)
        return case

    def transition(self, case_id: str, new_state: CaseState, **patch) -> dict[str, Any]:
        """Apply an ALLOWED state transition (optional field patches)."""
        case = self.store.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        cur = CaseState(case["state"])
        if new_state not in ALLOWED.get(cur, set()):
            raise TransitionError(f"{cur.value} -> {new_state.value} not allowed")
        case["state"] = new_state.value
        case["updated_at"] = _utcnow().isoformat(sep=" ")
        case.update({k: v for k, v in patch.items() if v is not None})
        self.store.save_case(case)
        return case

    def sign(self, case_id: str, signed_by: str, disposition: Disposition) -> dict[str, Any]:
        """Human-sign a disposition and move the case to CLOSED_SIGNED."""
        case = self.transition(
            case_id,
            CaseState.CLOSED_SIGNED,
            final_disposition=disposition.value,
            signed_by=signed_by,
            signed_at=_utcnow().isoformat(sep=" "),
        )
        return case

    def reopen(self, case_id: str, reason: str) -> dict[str, Any]:
        """Reopen months later — new case revision linked to prior."""
        prior = self.store.get_case(case_id)
        if not prior:
            raise KeyError(case_id)
        self.transition(case_id, CaseState.REOPENED, reopen_reason=reason)
        return self.create(
            event_id=prior["event_id"],
            tenant_code=prior["tenant_code"],
            reg_deadline_utc=None,  # notification already handled historically
            regulator_reportable=False,
            recommendation=Disposition(prior["recommendation"]) if prior.get("recommendation") else None,
            reopened_from=case_id,
            reopen_reason=reason,
        )

    def storm_safe_queue(self, tenant_code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """INC-2502: order by regulatory deadline so genuine cases aren't starved."""
        return self.store.queue(tenant_code=tenant_code, open_only=True, limit=limit)


# ====SHADOW====
"""Dr Rao gate: re-adjudicate past cases under a reference/rules change and diff."""


from copy import deepcopy
from typing import Any, Optional



def shadow_replay_bulletin(
    pack: DataPack,
    engine: AdjudicationEngine,
    *,
    firmware: str = BULLETIN_FW,
    bias_c: float = BULLETIN_BIAS_C,
    event_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Simulate April TT-CB-114 style change: ensure bulletin bias applied and diff outcomes.

    Baseline = engine as configured today (already applies bulletin).
    Alternate = force-disable bulletin correction to show what would have differed
    without the calibration notice — or re-run with bias forced on all matching FW.
    """
    events = pack.events
    if event_ids:
        idset = set(event_ids)
        events = [e for e in events if e.get("event_id") in idset]
    else:
        events = [e for e in events if str(e.get("logger_fw")) == firmware]

    diffs = []
    for e in events:
        baseline = engine.adjudicate(e)
        # Alternate: strip firmware so bulletin path does not fire
        alt_event = deepcopy(e)
        alt_event["logger_fw"] = "TT-DISABLED"
        alternate = engine.adjudicate(alt_event)
        if baseline.recommendation != alternate.recommendation or (
            baseline.corrected_max_temp_c != alternate.corrected_max_temp_c
        ):
            diffs.append(
                {
                    "event_id": e.get("event_id"),
                    "tenant_code": e.get("tenant_code"),
                    "firmware": e.get("logger_fw"),
                    "max_temp_c": e.get("max_temp_c"),
                    "with_bulletin": {
                        "recommendation": baseline.recommendation,
                        "corrected_max_temp_c": baseline.corrected_max_temp_c,
                    },
                    "without_bulletin": {
                        "recommendation": alternate.recommendation,
                        "corrected_max_temp_c": alternate.corrected_max_temp_c,
                    },
                    "historical_final": e.get("final_disposition"),
                }
            )
    return {
        "change": f"calibration bulletin {firmware} bias +{bias_c}°C (TT-CB-114 / INC-2506)",
        "candidates": len(events),
        "diffs": len(diffs),
        "diff_rows": diffs,
        "rao_gate": "Review diffs before promoting rule/reference change",
    }


# ====SERVICE====
"""Application service: ingest → adjudicate → evidence → case lifecycle."""


import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime-like value into a naive datetime, or None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if len(s) >= 19 else s, fmt)
        except ValueError:
            continue
    return None


# ====SERVICES====


class AdjudicationService:
    """Application façade: ingest → adjudicate → evidence → lifecycle → shadow."""
    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Construct store, evidence, and lifecycle from Settings."""
        self.settings = settings or get_settings()
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.store = BitemporalStore(self.settings.db_path)
        self.evidence = EvidenceStore(
            self.settings.evidence_dir,
            self.store,
            retention_years=self.settings.retention_years,
        )
        self.lifecycle = CaseLifecycle(self.store)
        self.pack: Optional[DataPack] = None
        self.engine: Optional[AdjudicationEngine] = None
        self.snapshot_id: Optional[str] = self.store.get_meta("ref_snapshot_id")

    def bootstrap(self, pack_path: Optional[Path] = None, *, reload: bool = False) -> str:
        """Load workbook into store (optional reload) and build the engine."""
        pack_path = Path(pack_path or self.settings.data_pack)
        if reload or not self.snapshot_id:
            # fresh DB if reload
            if reload and self.settings.db_path.exists():
                self.settings.db_path.unlink()
                self.store = BitemporalStore(self.settings.db_path)
                self.evidence = EvidenceStore(
                    self.settings.evidence_dir,
                    self.store,
                    retention_years=self.settings.retention_years,
                )
                self.lifecycle = CaseLifecycle(self.store)
            self.snapshot_id = load_workbook_into_store(pack_path, self.store)
        self.pack = DataPack.load(pack_path)
        self.engine = AdjudicationEngine(self.pack)
        return self.snapshot_id or ""

    def adjudicate_event(
        self,
        event_id: str,
        *,
        persist: bool = True,
        create_case: bool = True,
    ) -> dict[str, Any]:
        """Adjudicate one event; optionally persist evidence and open a case."""
        assert self.engine and self.pack and self.snapshot_id
        event = self.pack.event_by_id(event_id)
        if not event:
            raise KeyError(event_id)
        result = self.engine.adjudicate(event)
        bundle = None
        case = None
        if persist:
            bundle = self._persist(result, event)
            if create_case:
                case = self.lifecycle.create(
                    event_id=result.event_id,
                    tenant_code=result.tenant_code,
                    reg_deadline_utc=_parse_dt(result.reg_deadline_utc),
                    regulator_reportable=result.regulator_reportable,
                    recommendation=Disposition(result.recommendation),
                    evidence_bundle_id=bundle["bundle_id"],
                )
        return {
            "result": result,
            "bundle": bundle,
            "case": case,
        }

    def adjudicate_all(self, *, limit: Optional[int] = None, persist: bool = True) -> dict[str, Any]:
        """Adjudicate all (or limit) pack events; return rows and snapshot id."""
        assert self.engine and self.pack
        events = self.pack.events[: limit or len(self.pack.events)]
        rows = []
        for e in events:
            out = self.adjudicate_event(e["event_id"], persist=persist, create_case=persist)
            r: AdjudicationResult = out["result"]
            rows.append(
                {
                    "event_id": r.event_id,
                    "tenant_code": r.tenant_code,
                    "recommendation": r.recommendation,
                    "bundle_id": (out["bundle"] or {}).get("bundle_id"),
                    "case_id": (out["case"] or {}).get("case_id"),
                    "reg_deadline_utc": r.reg_deadline_utc,
                }
            )
        return {"count": len(rows), "rows": rows, "snapshot_id": self.snapshot_id}

    def _persist(self, result: AdjudicationResult, event: dict[str, Any]) -> dict[str, Any]:
        """Write an evidence bundle for a result and return bundle metadata."""
        assert self.snapshot_id
        inputs = {
            "alert": {
                "event_id": event.get("event_id"),
                "alert_ts_utc": str(event.get("alert_ts_utc")),
                "excursion_start_utc": str(event.get("excursion_start_utc")),
                "temps": {
                    "min": event.get("min_temp_c"),
                    "max": event.get("max_temp_c"),
                    "duration_min": event.get("duration_min"),
                },
                "logger_fw": event.get("logger_fw"),
                "logger_id": event.get("logger_id"),
                "product_ref_as_received": event.get("product_ref_as_received"),
                "carrier_ref_as_received": event.get("carrier_ref_as_received"),
                "lane_text": event.get("lane_text"),
                "temperature_series_ref": f"pack:01_Excursion_Events:{event.get('event_id')}",
            },
            "resolution": result.evidence,
            "lane_history_ref": {
                "prior_excursions_lane_90d": event.get("prior_excursions_lane_90d"),
                "note": "full lane panel is production backlog; count from alert row used",
            },
        }
        recommendation = {
            "disposition": result.recommendation,
            "requires_human_signature": result.requires_human_signature,
            "confidence": result.confidence,
            "triage_label": result.triage_label,
            "corrected_max_temp_c": result.corrected_max_temp_c,
            "bulletin_applied": result.bulletin_applied,
            "regulator_reportable": result.regulator_reportable,
            "reg_window_hours": result.reg_window_hours,
            "reg_deadline_utc": result.reg_deadline_utc,
        }
        return self.evidence.write_bundle(
            tenant_code=result.tenant_code,
            event_id=result.event_id,
            recommendation=recommendation,
            inputs=inputs,
            reasoning_steps=list(result.rationale),
            rule_pack_version=self.settings.rule_pack_version,
            ref_snapshot_id=self.snapshot_id,
            code_version=self.settings.code_version,
        )

    def full_basis(self, event_id: str, tenant_code: str) -> dict[str, Any]:
        """Produce the full reconstructable evidence basis for an event/tenant."""
        return self.evidence.produce_full_basis(event_id, tenant_code)

    def verify_tenant_chain(self, tenant_code: str) -> dict[str, Any]:
        """Verify the append-only evidence hash chain for a tenant."""
        return self.evidence.verify_chain(tenant_code)

    def replay_from_bundle(self, bundle_id: str, tenant_code: str) -> dict[str, Any]:
        """Re-run adjudication from bundle inputs; require identical disposition."""
        assert self.engine and self.pack
        doc = self.evidence.get(bundle_id, tenant_code=tenant_code)
        event_id = doc["event_id"]
        event = self.pack.event_by_id(event_id)
        assert event
        again = self.engine.adjudicate(event)
        original = doc["recommendation"]["disposition"]
        return {
            "bundle_id": bundle_id,
            "original_disposition": original,
            "replay_disposition": again.recommendation,
            "identical": original == again.recommendation,
            "original_reasoning": doc.get("reasoning_steps"),
            "replay_reasoning": again.rationale,
            "versions": {
                "rule_pack_version": doc.get("rule_pack_version"),
                "ref_snapshot_id": doc.get("ref_snapshot_id"),
                "code_version": doc.get("code_version"),
            },
        }

    def shadow_bulletin(self) -> dict[str, Any]:
        """Run TT-CB-114 shadow replay and return the diff report."""
        assert self.engine and self.pack
        return shadow_replay_bulletin(self.pack, self.engine)

    def as_of_sop(self, tenant_code: str, as_of_date: str, title: str = "Temperature Excursion Management") -> dict[str, Any]:
        """Look up SOP-in-force for tenant/title on an ISO date string."""
        d = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        return self.store.sop_in_force(tenant_code, title, d)

    def agreement_report(self) -> dict[str, Any]:
        """Stratify engine vs historical final / assistant agreement across the pack.

        Agreement with ``final_disposition`` is computed on the 200 rows that have a
        non-empty historical final (the human-opened stratum). Assistant agreement
        uses ``rules_engine_recommendation`` across all 420 rows (pack README: that
        column is the LLM assistant draft since 2024).
        """
        assert self.engine and self.pack
        n_all = 0
        n_final = 0
        agree_final = 0
        agree_assistant = 0
        by_reason: Counter[str] = Counter()
        by_tenant: Counter[str] = Counter()
        by_firmware: Counter[str] = Counter()
        by_product: Counter[str] = Counter()
        disagree_rows: list[dict[str, Any]] = []
        agree_ids: list[str] = []
        t0 = time.perf_counter()
        for event in self.pack.events:
            result = self.engine.adjudicate(event)
            n_all += 1
            hist_final = str(event.get("final_disposition") or "").strip()
            assistant = str(event.get("rules_engine_recommendation") or "").strip()
            if assistant and result.recommendation == assistant:
                agree_assistant += 1
            if not hist_final:
                continue
            n_final += 1
            if result.recommendation == hist_final:
                agree_final += 1
                agree_ids.append(result.event_id)
                continue
            pair = f"{hist_final}->{result.recommendation}"
            by_reason[pair] += 1
            by_tenant[str(event.get("tenant_code") or "unknown")] += 1
            by_firmware[str(event.get("logger_fw") or "unknown")] += 1
            product = result.product_brand or str(event.get("product_ref_as_received") or "unknown")
            by_product[product[:48]] += 1
            if len(disagree_rows) < 40:
                disagree_rows.append(
                    {
                        "event_id": result.event_id,
                        "tenant_code": result.tenant_code,
                        "engine": result.recommendation,
                        "historical_final": hist_final,
                        "assistant": assistant or None,
                        "firmware": event.get("logger_fw"),
                        "product": product,
                        "triage_label": result.triage_label,
                        "rationale_head": list(result.rationale[:3]),
                    }
                )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "events_total": n_all,
            "events_with_historical_final": n_final,
            "agree_with_historical_final": agree_final,
            "agree_with_historical_final_pct": round(100.0 * agree_final / n_final, 2) if n_final else 0.0,
            "agree_with_assistant": agree_assistant,
            "agree_with_assistant_pct": round(100.0 * agree_assistant / n_all, 2) if n_all else 0.0,
            "disagree_by_reason": dict(by_reason.most_common()),
            "disagree_by_tenant": dict(by_tenant.most_common()),
            "disagree_by_firmware": dict(by_firmware.most_common()),
            "disagree_by_product": dict(by_product.most_common(15)),
            "agree_event_ids": agree_ids,
            "disagree_samples": disagree_rows,
            "elapsed_ms": elapsed_ms,
            "notes": [
                "7% headline uses the 200 non-empty final_disposition rows (case_opened stratum), not all 420.",
                "Low final agreement is expected: engine escalates Refer-QA / unreadable / presentation mismatch rather than guessing RELEASE.",
                "rules_engine_recommendation is the assistant draft since 2024 (pack README), not the 2023 rules engine.",
            ],
        }

    def health_report(self, *, baseline_mix: Optional[dict[str, int]] = None) -> dict[str, Any]:
        """Compute 3am-style operational signals from the loaded pack + evidence store.

        Signals covered (prototype scope): regulatory deadline at-risk/breached on the
        pack's reportable rows, evidence chain verification across tenants that have
        bundles, decision-mix vs a baseline distribution, and data-feed staleness of the
        workbook extract. Queue age and firmware-bulletin change hooks are surfaced as
        structured checks with thresholds even when the pack cannot fully drive them.
        """
        assert self.engine and self.pack
        if baseline_mix is None:
            baseline_mix = {
                "AUTO_CLOSE": 224,
                "ESCALATED_TO_SENIOR_QA": 80,
                "RELEASE_WITH_NOTE": 54,
                "DESTROY": 31,
                "QUARANTINE_PENDING_LAB": 31,
            }
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mix: Counter[str] = Counter()
        deadline_breached = 0
        deadline_at_risk = 0
        reportable = 0
        queue_ages_hours: list[float] = []
        firmware_counts: Counter[str] = Counter()
        for event in self.pack.events:
            result = self.engine.adjudicate(event)
            mix[result.recommendation] += 1
            firmware_counts[str(event.get("logger_fw") or "unknown")] += 1
            if result.regulator_reportable:
                reportable += 1
                # Pack historical late filings (reported_within_window = N)
                if str(event.get("reported_within_window") or "").upper() in {"N", "NO", "FALSE", "0"}:
                    deadline_breached += 1
                # Prototype at-risk: open reportable cases whose deadline is within 6h
                # of "now" relative to alert+window (cannot truly page from static pack).
                deadline = _parse_dt(result.reg_deadline_utc)
                alert_ts = event.get("_alert_ts") or _parse_dt(str(event.get("alert_ts_utc") or ""))
                if deadline is not None and alert_ts is not None:
                    # Use historical hours_to_notification when present
                    hours_to = event.get("hours_to_notification")
                    try:
                        if hours_to is not None and float(hours_to) >= 0:
                            queue_ages_hours.append(float(hours_to))
                    except (TypeError, ValueError):
                        pass
                    window_h = result.reg_window_hours or 72.0
                    # Flag rows historically inside last 25% of window without notification as at-risk pattern
                    if str(event.get("reported_within_window") or "").upper() in {"Y", "YES", "TRUE", "1"}:
                        try:
                            if hours_to is not None and float(hours_to) >= 0.75 * float(window_h):
                                deadline_at_risk += 1
                        except (TypeError, ValueError):
                            pass

        # Evidence chains for tenants that currently have bundles
        chain_results: dict[str, Any] = {}
        chain_failures = 0
        tenants = sorted({str(e.get("tenant_code")) for e in self.pack.events if e.get("tenant_code")})
        for tenant in tenants:
            try:
                vr = self.evidence.verify_chain(tenant)
            except Exception as exc:  # noqa: BLE001 — health must not crash
                vr = {"ok": False, "error": str(exc)}
            chain_results[tenant] = vr
            if vr.get("ok") is False and vr.get("length", 0) not in (0, None):
                chain_failures += 1
            # empty chain is ok (no bundles yet)

        # Decision-mix drift vs baseline (absolute count delta / total)
        total = sum(mix.values()) or 1
        drift: dict[str, Any] = {}
        max_abs_drift_pct = 0.0
        for key in sorted(set(baseline_mix) | set(mix)):
            base = baseline_mix.get(key, 0)
            got = mix.get(key, 0)
            delta = got - base
            drift_pct = 100.0 * abs(delta) / total
            drift[key] = {"baseline": base, "observed": got, "delta": delta, "abs_pct_of_pack": round(drift_pct, 3)}
            max_abs_drift_pct = max(max_abs_drift_pct, drift_pct)

        # Feed staleness: pack extract date from workbook meta if present, else mtime
        pack_path = Path(self.settings.data_pack)
        pack_mtime = datetime.fromtimestamp(pack_path.stat().st_mtime) if pack_path.exists() else None
        pack_age_hours = (
            (datetime.now() - pack_mtime).total_seconds() / 3600.0 if pack_mtime else None
        )

        alerts: list[dict[str, Any]] = []

        def _alert(
            name: str,
            severity: str,
            metric: Any,
            threshold: str,
            page: str,
            runbook: str,
            firing: bool,
        ) -> None:
            alerts.append(
                {
                    "name": name,
                    "severity": severity,
                    "metric": metric,
                    "threshold": threshold,
                    "page": page,
                    "runbook_step": runbook,
                    "firing": firing,
                }
            )

        _alert(
            "regulatory_deadline_breached",
            "P1",
            {"breached_in_pack": deadline_breached, "reportable": reportable},
            "breached > 0 on live traffic (board commitment 5: zero late filings)",
            "Regulatory Affairs on-call + QA Lead (Kavitha Reddy role)",
            "Pull storm-safe queue ordered by reg_deadline_utc; file notification from evidence bundle; open INC; do not wait for disposition.",
            deadline_breached > 0,
        )
        _alert(
            "regulatory_deadline_at_risk",
            "P2",
            {"at_risk_pattern_rows": deadline_at_risk},
            "any reportable case with <25% of window remaining and no notification artefact",
            "QA reviewer shift lead",
            "Promote case to front of queue; attach partial evidence; draft notification; page Regulatory if <6h remain.",
            deadline_at_risk > 0,
        )
        _alert(
            "evidence_chain_verification_failure",
            "P1",
            {"tenants_failed": chain_failures, "per_tenant": {t: v.get("ok") for t, v in chain_results.items()}},
            "verify_chain ok == false for any tenant with length > 0",
            "Platform on-call",
            "Freeze sign-off for that tenant; restore evidence dir from WORM snapshot; re-verify; invalidate suspect bundle ids.",
            chain_failures > 0,
        )
        _alert(
            "decision_mix_drift",
            "P1",
            {"max_abs_drift_pct": round(max_abs_drift_pct, 3), "mix": dict(mix), "drift": drift},
            "any disposition share drifts >5pp vs approved baseline (INC-2411 class)",
            "Platform on-call + Dr Rao delegate",
            "Halt rule_pack promotion; run shadow replay on golden set; publish diff; require Rao sign-off before re-enable.",
            max_abs_drift_pct > 5.0,
        )
        _alert(
            "data_feed_staleness",
            "P2",
            {"pack_path": str(pack_path), "pack_age_hours": None if pack_age_hours is None else round(pack_age_hours, 2)},
            "reference feed age >24h in production (prototype: workbook mtime)",
            "Data Services on-call",
            "Check ThermaTrace/ERP/Docuvault connectors; if pack-only lab mode, re-run ingest --reload after feed repair.",
            bool(pack_age_hours is not None and pack_age_hours > 24),
        )
        max_queue_age = max(queue_ages_hours) if queue_ages_hours else 0.0
        _alert(
            "queue_age",
            "P2",
            {
                "max_hours_to_notification_in_pack": round(max_queue_age, 2),
                "n_measured": len(queue_ages_hours),
            },
            "open actionable age >12h OR any reportable age >50% of its window (INC-2502)",
            "QA shift lead",
            "Enable storm brake; auto-close only facility/duplicate heuristics; drain by reg_deadline_utc ASC.",
            max_queue_age > 12,
        )
        bulletin_fw = "TT-2.14.3"
        _alert(
            "firmware_bulletin_change",
            "P2",
            {"watched_firmware": bulletin_fw, "events_on_fw": firmware_counts.get(bulletin_fw, 0), "firmware_histogram": dict(firmware_counts)},
            "vendor bulletin hash/version changes vs last approved ref_snapshot",
            "Platform on-call + Marieke de Vries notified on version change (Aurastat ask)",
            "Run shadow-bulletin; open Dr Rao gate; re-adjudicate affected firmware cohort; withdraw carrier invoices if liability flips (INC-2506).",
            False,  # static pack: no live bulletin feed; hook is ready
        )

        return {
            "ok": not any(a["firing"] and a["severity"] == "P1" for a in alerts if a["name"] != "regulatory_deadline_breached"),
            "generated_at_utc": now.isoformat(sep=" "),
            "decision_mix": dict(sorted(mix.items())),
            "baseline_mix": baseline_mix,
            "reportable_in_pack": reportable,
            "deadline_breached_in_pack": deadline_breached,
            "deadline_at_risk_pattern_rows": deadline_at_risk,
            "chain_verification": chain_results,
            "alerts": alerts,
            "note": "Pack is stratified historical data; breached/at-risk counts here demonstrate the monitor against known INC/late rows, not live pages.",
        }



# ====API====
# FastAPI + Pydantic v2 are imported lazily so engine/CLI/tests work with openpyxl only.
# Models are installed into module globals before route registration so that
# `from __future__ import annotations` string annotations still resolve for FastAPI.

AdjudicateRequest: Any = None
BasisRequest: Any = None
VerifyRequest: Any = None
ReplayRequest: Any = None
HealthResponse: Any = None


def _load_api_models() -> None:
    """Lazily define Pydantic v2 request/response models in module globals."""
    global AdjudicateRequest, BasisRequest, VerifyRequest, ReplayRequest, HealthResponse
    if AdjudicateRequest is not None:
        return
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover
        raise DependencyMissingError(
            "API layer requires: pip install fastapi pydantic uvicorn  "
            "(engine/CLI/tests still run with only openpyxl)"
        ) from exc

    class _AdjudicateRequest(BaseModel):
        """POST /adjudicate body."""

        event_id: str = Field(..., min_length=1)
        persist: bool = True

    class _BasisRequest(BaseModel):
        """POST /evidence/basis body."""

        event_id: str = Field(..., min_length=1)
        tenant_code: str = Field(..., min_length=1)

    class _VerifyRequest(BaseModel):
        """POST /evidence/verify body."""

        tenant_code: str = Field(..., min_length=1)

    class _ReplayRequest(BaseModel):
        """POST /replay body."""

        bundle_id: str = Field(..., min_length=1)
        tenant_code: str = Field(..., min_length=1)

    class _HealthResponse(BaseModel):
        """GET /health payload."""

        ok: bool
        snapshot_id: Optional[str] = None
        rule_pack_version: str

    AdjudicateRequest = _AdjudicateRequest
    BasisRequest = _BasisRequest
    VerifyRequest = _VerifyRequest
    ReplayRequest = _ReplayRequest
    HealthResponse = _HealthResponse


def _require_fastapi() -> tuple[Any, Any, Any]:
    """Import FastAPI stack or raise a clear DependencyMissingError."""
    try:
        from fastapi import Depends, FastAPI, HTTPException, Query, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - depends on env
        raise DependencyMissingError(
            "API layer requires: pip install fastapi pydantic uvicorn  "
            "(engine/CLI/tests still run with only openpyxl)"
        ) from exc
    _load_api_models()
    return FastAPI, HTTPException, (Depends, Query, Request, JSONResponse)


def create_app(svc: Optional[AdjudicationService] = None) -> Any:
    """Build a FastAPI application with DI-held AdjudicationService and typed routes.

    Lazy-imports FastAPI/Pydantic. Returns the app instance (not a server).
    """
    FastAPI, HTTPException, extras = _require_fastapi()
    Depends, Query, Request, JSONResponse = extras

    service = svc or AdjudicationService()
    if service.engine is None:
        service.bootstrap()

    app = FastAPI(
        title="Kestrel Sentinel Adjudication API",
        version=service.settings.code_version,
        description="As-of adjudication, evidence basis, shadow replay, queue.",
    )
    app.state.svc = service

    def get_svc() -> AdjudicationService:
        """FastAPI dependency: shared AdjudicationService."""
        return app.state.svc

    @app.exception_handler(TenantIsolationError)
    async def _tenant_exc(_request: Request, exc: TenantIsolationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(PermissionError)
    async def _perm_exc(_request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _nf_exc(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def _fnf_exc(_request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(KeyError)
    async def _key_exc(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": f"unknown entity {exc}"})

    @app.exception_handler(ValidationAppError)
    async def _val_exc(_request: Request, exc: ValidationAppError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/health", response_model=HealthResponse)
    def health(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Liveness + rule-pack identity."""
        return {
            "ok": True,
            "snapshot_id": svc_dep.snapshot_id,
            "rule_pack_version": svc_dep.settings.rule_pack_version,
        }

    @app.post("/adjudicate")
    def adjudicate(
        payload: AdjudicateRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Adjudicate one event and optionally persist evidence + case."""
        try:
            out = svc_dep.adjudicate_event(payload.event_id, persist=payload.persist)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown event {payload.event_id}") from exc
        r = out["result"]
        case = out.get("case") or {}
        return {
            "event_id": r.event_id,
            "tenant_code": r.tenant_code,
            "recommendation": r.recommendation,
            "confidence": r.confidence,
            "rationale": r.rationale,
            "requires_human_signature": r.requires_human_signature,
            "bundle_id": (out["bundle"] or {}).get("bundle_id"),
            "case_id": case.get("case_id"),
            "case_state": case.get("state"),
            "reg_deadline_utc": r.reg_deadline_utc,
        }

    @app.post("/cases/{case_id}/sign")
    def sign_case(
        case_id: str,
        signed_by: str = Query(..., min_length=1),
        disposition: str = Query(..., min_length=1),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Lifecycle: human sign-off on a recommended / auto-close case."""
        try:
            disp = Disposition(disposition)
            case = svc_dep.lifecycle.sign(case_id, signed_by=signed_by, disposition=disp)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}") from exc
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case

    @app.post("/cases/{case_id}/reopen")
    def reopen_case(
        case_id: str,
        reason: str = Query("reopened", min_length=1),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Lifecycle: reopen a closed case (bulletin / customer / audit)."""
        try:
            case = svc_dep.lifecycle.reopen(case_id, reason=reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}") from exc
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Fetch one case record."""
        case = svc_dep.store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}")
        return case

    @app.get("/evidence/{bundle_id}")
    def get_evidence(
        bundle_id: str,
        tenant_code: str = Query(...),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Fetch one evidence bundle with tenant isolation."""
        try:
            return svc_dep.evidence.get(bundle_id, tenant_code=tenant_code, measure=True)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evidence/basis")
    def evidence_basis(
        payload: BasisRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Board commitment 3 — full reconstructable basis."""
        try:
            return svc_dep.full_basis(payload.event_id, payload.tenant_code)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evidence/verify")
    def evidence_verify(
        payload: VerifyRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Verify per-tenant evidence hash chain."""
        return svc_dep.verify_tenant_chain(payload.tenant_code)

    @app.post("/replay")
    def replay(
        payload: ReplayRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Replay adjudication from a stored bundle."""
        try:
            return svc_dep.replay_from_bundle(payload.bundle_id, payload.tenant_code)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/shadow/bulletin")
    def shadow_bulletin(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Dr Rao gate — TT-CB-114 shadow diff summary."""
        report = svc_dep.shadow_bulletin()
        return {
            "change": report["change"],
            "candidates": report["candidates"],
            "diffs": report["diffs"],
            "sample_diffs": report["diff_rows"][:20],
            "rao_gate": report["rao_gate"],
        }

    @app.get("/queue")
    def queue(
        tenant_code: Optional[str] = Query(None),
        limit: int = Query(20, ge=1, le=500),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Storm-safe priority queue ordered by regulatory deadline."""
        return {"items": svc_dep.lifecycle.storm_safe_queue(tenant_code=tenant_code, limit=limit)}

    @app.get("/as-of/sop")
    def as_of_sop(
        tenant_code: str = Query(...),
        date: str = Query(..., description="YYYY-MM-DD"),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """SOP in force as-at a date (AUD-2603 shape)."""
        return svc_dep.as_of_sop(tenant_code, date)

    @app.get("/ops/health-report")
    def ops_health_report(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Full 3am monitoring catalog (same payload as CLI `health`)."""
        return svc_dep.health_report()

    @app.get("/ops/agreement")
    def ops_agreement(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Agreement stratification (same payload as CLI `agreement`)."""
        return svc_dep.agreement_report()

    return app


def serve_http(
    svc: AdjudicationService,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Serve the FastAPI app with uvicorn (lazy import)."""
    if svc.engine is None:
        svc.bootstrap()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise DependencyMissingError(
            "serve requires: pip install fastapi pydantic uvicorn"
        ) from exc
    app = create_app(svc)
    logging.getLogger("kestrel.http").info("serving on http://%s:%s (uvicorn/FastAPI)", host, port)
    uvicorn.run(app, host=host, port=port, log_level=svc.settings.log_level.lower())


def _http_request(
    method: str,
    path: str,
    svc: AdjudicationService,
    body: Optional[dict[str, Any]] = None,
    query: Optional[dict[str, str]] = None,
) -> tuple[int, Any]:
    """In-process API helper via FastAPI TestClient when httpx is available."""
    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI TestClient unavailable — pip install fastapi pydantic httpx"
        ) from exc
    app = create_app(svc)
    client = TestClient(app)
    if method.upper() == "GET":
        resp = client.get(path, params=query or None)
    else:
        resp = client.post(path, json=body or {})
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": resp.text}
    if resp.status_code >= 400 and isinstance(payload, dict) and "detail" in payload and "error" not in payload:
        detail = payload["detail"]
        payload = {"error": detail if isinstance(detail, str) else str(detail)}
    return resp.status_code, payload


# =============================================================================
# CLI
# =============================================================================


def _default_work_dir() -> Path:
    """Return the temp working directory for DB/evidence/CSV outputs (created if needed)."""
    d = Path(tempfile.gettempdir()) / "kestrel-adjudication"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _svc_from_args(args: argparse.Namespace) -> AdjudicationService:
    """Build an AdjudicationService from argparse namespace overrides."""
    settings = get_settings()
    if getattr(args, "db", None):
        settings.db_path = Path(args.db)
    else:
        settings.db_path = _default_work_dir() / "kestrel.sqlite"
    if getattr(args, "pack", None):
        settings.data_pack = Path(args.pack)
    if getattr(args, "evidence_dir", None):
        settings.evidence_dir = Path(args.evidence_dir)
    else:
        settings.evidence_dir = _default_work_dir() / "evidence"
    if getattr(args, "log_level", None):
        settings.log_level = args.log_level
    setup_logging(settings.log_level)
    return AdjudicationService(settings)


def main(argv: Optional[list[str]] = None) -> int:
    """Argparse CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="kestrel",
        description="Kestrel Sentinel — as-of adjudication & evidence platform (single file)",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: temp dir)")
    parser.add_argument("--pack", type=Path, default=None, help="Workbook path")
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("ingest", help="Load workbook into bitemporal store")
    p_boot.add_argument("--reload", action="store_true")

    p_adj = sub.add_parser("adjudicate", help="Adjudicate one event or a limited batch")
    p_adj.add_argument("--event", type=str, default=None)
    p_adj.add_argument("--limit", type=int, default=None)
    p_adj.add_argument("--no-persist", action="store_true")
    p_adj.add_argument("--out", type=Path, default=None)

    p_all = sub.add_parser("run-all", help="Adjudicate all 420 events; print disposition counts")
    p_all.add_argument("--no-persist", action="store_true")
    p_all.add_argument("--out", type=Path, default=None)

    p_basis = sub.add_parser("basis", help="Full evidence basis for an event")
    p_basis.add_argument("--event", required=True)
    p_basis.add_argument("--tenant", required=True)
    p_basis.add_argument("--out", type=Path, default=None)

    p_verify = sub.add_parser("verify", help="Verify tenant evidence hash chain")
    p_verify.add_argument("--tenant", required=True)

    p_replay = sub.add_parser("replay", help="Replay decision from evidence bundle")
    p_replay.add_argument("--bundle", required=True)
    p_replay.add_argument("--tenant", required=True)

    p_shadow = sub.add_parser("shadow-bulletin", help="Dr Rao gate: TT-CB-114 shadow diff")
    p_shadow.add_argument("--out", type=Path, default=None)

    p_queue = sub.add_parser("queue", help="Storm-safe priority queue")
    p_queue.add_argument("--tenant", default=None)
    p_queue.add_argument("--limit", type=int, default=20)

    p_asof = sub.add_parser("as-of-sop", help="SOP in force as-at a date")
    p_asof.add_argument("--tenant", required=True)
    p_asof.add_argument("--date", required=True, help="YYYY-MM-DD")

    p_api = sub.add_parser("serve", help="Run FastAPI+uvicorn HTTP API (lazy deps)")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    p_health = sub.add_parser("health", help="3am ops signals: deadlines, chain, mix drift, feed age")
    sub.add_parser("monitor", help="Alias for health")
    sub.add_parser("agreement", help="Stratify engine vs historical final/assistant agreement")

    sub.add_parser("test", help="Run embedded unittest suite (≥28 tests)")
    sub.add_parser("selftest", help="Alias for test")

    args = parser.parse_args(argv)

    if args.cmd in {"test", "selftest"}:
        return _run_tests()

    svc = _svc_from_args(args)

    if args.cmd == "ingest":
        snap = svc.bootstrap(reload=args.reload)
        print(
            json.dumps(
                {"snapshot_id": snap, "alerts": svc.store.get_meta("loaded_alerts")},
                indent=2,
            )
        )
        return 0

    if args.cmd == "serve":
        serve_http(svc, host=args.host or svc.settings.api_host, port=args.port or svc.settings.api_port)
        return 0

    svc.bootstrap()

    if args.cmd == "adjudicate":
        out_path = args.out or (_default_work_dir() / "adjudication_results.csv")
        if args.event:
            out = svc.adjudicate_event(args.event, persist=not args.no_persist)
            r = out["result"]
            print(
                json.dumps(
                    {
                        "event_id": r.event_id,
                        "recommendation": r.recommendation,
                        "confidence": r.confidence,
                        "bundle_id": (out["bundle"] or {}).get("bundle_id"),
                        "case_id": (out["case"] or {}).get("case_id"),
                        "rationale": r.rationale,
                    },
                    indent=2,
                    default=str,
                )
            )
            return 0
        summary = svc.adjudicate_all(limit=args.limit, persist=not args.no_persist)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "event_id",
                    "tenant_code",
                    "recommendation",
                    "bundle_id",
                    "case_id",
                    "reg_deadline_utc",
                ],
            )
            w.writeheader()
            for row in summary["rows"]:
                w.writerow(row)
        counts = Counter(r["recommendation"] for r in summary["rows"])
        print(
            json.dumps(
                {
                    "count": summary["count"],
                    "out": str(out_path),
                    "snapshot_id": summary["snapshot_id"],
                    "counts": dict(counts),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "run-all":
        out_path = args.out or (_default_work_dir() / "adjudication_results.csv")
        summary = svc.adjudicate_all(persist=not args.no_persist)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "event_id",
                    "tenant_code",
                    "recommendation",
                    "bundle_id",
                    "case_id",
                    "reg_deadline_utc",
                ],
            )
            w.writeheader()
            for row in summary["rows"]:
                w.writerow(row)
        counts = Counter(r["recommendation"] for r in summary["rows"])
        # showcase EXC-107133
        gold = next((r for r in summary["rows"] if r["event_id"] == "EXC-107133"), None)
        print(
            json.dumps(
                {
                    "count": summary["count"],
                    "counts": dict(sorted(counts.items())),
                    "EXC-107133": gold,
                    "out": str(out_path),
                    "snapshot_id": summary["snapshot_id"],
                },
                indent=2,
                default=str,
            )
        )
        return 0

    if args.cmd == "basis":
        basis = svc.full_basis(args.event, args.tenant)
        out = args.out or (_default_work_dir() / f"basis_{args.event}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(basis, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "event_id": args.event,
                    "bundle_id": basis["bundle"]["bundle_id"],
                    "retrieval_latency_ms": basis["retrieval_latency_ms"],
                    "within_one_hour": basis["within_one_hour"],
                    "retention_until": basis["retention_until"],
                    "wrote": str(out),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "verify":
        print(json.dumps(svc.verify_tenant_chain(args.tenant), indent=2))
        return 0

    if args.cmd == "replay":
        print(json.dumps(svc.replay_from_bundle(args.bundle, args.tenant), indent=2, default=str))
        return 0

    if args.cmd == "shadow-bulletin":
        report = svc.shadow_bulletin()
        out = args.out or (_default_work_dir() / "shadow_bulletin_diff.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "change": report["change"],
                    "candidates": report["candidates"],
                    "diffs": report["diffs"],
                    "wrote": str(out),
                    "rao_gate": report["rao_gate"],
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "queue":
        q = svc.lifecycle.storm_safe_queue(tenant_code=args.tenant, limit=args.limit)
        print(json.dumps(q, indent=2, default=str))
        return 0

    if args.cmd == "as-of-sop":
        hit = svc.as_of_sop(args.tenant, args.date)
        rec = hit.get("record")
        print(
            json.dumps(
                {
                    "tenant": args.tenant,
                    "as_of": args.date,
                    "overlap_conflict": hit.get("overlap_conflict"),
                    "selected": None
                    if not rec
                    else {
                        "doc_id": rec["payload"].get("doc_id"),
                        "revision": rec["payload"].get("revision"),
                        "valid_from": rec.get("valid_from"),
                        "valid_to": rec.get("valid_to"),
                    },
                    "competing_revisions": [
                        c["payload"].get("revision") for c in hit.get("competing") or []
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.cmd in {"health", "monitor"}:
        report = svc.health_report()
        print(json.dumps(report, indent=2, default=str))
        return 0

    if args.cmd == "agreement":
        report = svc.agreement_report()
        # Compact headline for humans; full JSON still printed
        headline = {
            "events_total": report["events_total"],
            "events_with_historical_final": report["events_with_historical_final"],
            "agree_with_historical_final": report["agree_with_historical_final"],
            "agree_with_historical_final_pct": report["agree_with_historical_final_pct"],
            "agree_with_assistant": report["agree_with_assistant"],
            "agree_with_assistant_pct": report["agree_with_assistant_pct"],
            "disagree_by_reason_top": list(report["disagree_by_reason"].items())[:8],
            "disagree_by_tenant": report["disagree_by_tenant"],
            "disagree_by_firmware": report["disagree_by_firmware"],
            "notes": report["notes"],
            "full_keys": sorted(report.keys()),
        }
        print(json.dumps({"headline": headline, "report": report}, indent=2, default=str))
        return 0

    return 1


# =============================================================================
# Embedded unittest suite (≥28 tests — parity with prior package + prototype)
# =============================================================================


def _make_tmp_svc(tmpdir: Path) -> AdjudicationService:
    """Create a bootstrapped service rooted at tmpdir for unit tests."""
    settings = Settings(
        data_pack=_DEFAULT_PACK,
        db_path=tmpdir / "t.sqlite",
        evidence_dir=tmpdir / "evidence",
        log_level="WARNING",
        rule_pack_version="0.3.0",
        code_version="0.3.0",
        retention_years=7,
    )
    svc = AdjudicationService(settings)
    svc.bootstrap(reload=True)
    return svc


class _KestrelTestCase(unittest.TestCase):
    """Shared fixture: fresh temp DB + evidence dir per test class or method."""

    svc: AdjudicationService
    _tmpdir: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        """Create a temporary DB/evidence dir and bootstrap a shared service."""
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="kestrel-test-")
        cls.svc = _make_tmp_svc(Path(cls._tmpdir.name))

    @classmethod
    def tearDownClass(cls) -> None:
        """Remove the temporary test directory."""
        cls._tmpdir.cleanup()


class TestGoldenExc107133(_KestrelTestCase):
    """Golden tests for hero case EXC-107133 (RELEASE_WITH_NOTE)."""
    def test_exc_107133_release_with_note(self) -> None:
        """Persist EXC-107133 and assert RELEASE_WITH_NOTE plus GTIN evidence."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        self.assertEqual(out["result"].recommendation, RELEASE_WITH_NOTE)
        self.assertTrue(out["bundle"]["bundle_id"].startswith("EVB-"))
        self.assertEqual(out["bundle"]["inputs"]["resolution"]["product"]["gtin"], "08901234500035")

    def test_exc_107133_brief_narrative(self) -> None:
        """Assert brief narrative fields: signature required, no bulletin, 11.2 °C."""
        ev = self.svc.pack.event_by_id("EXC-107133")  # type: ignore[union-attr]
        assert ev is not None
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertEqual(r.recommendation, RELEASE_WITH_NOTE)
        self.assertTrue(r.requires_human_signature)
        self.assertFalse(r.bulletin_applied)
        self.assertEqual(r.corrected_max_temp_c, 11.2)
        self.assertIsNotNone(r.evidence.get("product"))
        self.assertTrue(r.reg_deadline_utc or r.reg_window_hours)


class TestAPISmoke(_KestrelTestCase):
    """In-process FastAPI TestClient smoke tests (skip if httpx/fastapi missing)."""

    def _req(self, *args: Any, **kwargs: Any) -> tuple[int, Any]:
        """Wrap _http_request and skip the test when FastAPI/httpx are absent."""
        try:
            return _http_request(*args, **kwargs)
        except (RuntimeError, DependencyMissingError) as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def test_api_health_adjudicate_basis(self) -> None:
        """Exercise /health, /adjudicate, /evidence/basis, cross-tenant 403, /replay."""
        code, health = self._req("GET", "/health", self.svc)
        self.assertEqual(code, 200)
        self.assertTrue(health["ok"])
        code, body = self._req(
            "POST", "/adjudicate", self.svc, {"event_id": "EXC-107133", "persist": True}
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["recommendation"], RELEASE_WITH_NOTE)
        bundle_id = body["bundle_id"]
        code, b = self._req(
            "POST",
            "/evidence/basis",
            self.svc,
            {"event_id": "EXC-107133", "tenant_code": "T-KAVERI"},
        )
        self.assertEqual(code, 200)
        self.assertGreaterEqual(b["retrieval_latency_ms"], 0)
        code, denied = self._req(
            "GET", f"/evidence/{bundle_id}", self.svc, query={"tenant_code": "T-MERIDIAN"}
        )
        self.assertEqual(code, 403)
        code, ok = self._req(
            "POST",
            "/replay",
            self.svc,
            {"bundle_id": bundle_id, "tenant_code": "T-KAVERI"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(ok["identical"])


class TestBitemporalAsOf(_KestrelTestCase):
    """Bitemporal SOP as-at lookups (Aura AUD-2603 date, Kaveri overlap)."""
    def test_aura_sop_as_of_audit_date(self) -> None:
        """SOP in force for T-AURA on 2025-08-14 must be answerable."""
        hit = self.svc.store.sop_in_force(
            "T-AURA", "Temperature Excursion Management", date(2025, 8, 14)
        )
        self.assertIsNotNone(hit["record"])
        self.assertTrue(hit["record"]["payload"]["doc_id"])
        vf = hit["record"]["valid_from"][:10]
        self.assertLessEqual(vf, "2025-08-14")

    def test_kaveri_sop_overlap(self) -> None:
        """T-KAVERI Temperature Excursion Management overlaps on 2026-07-28."""
        hit = self.svc.store.sop_in_force(
            "T-KAVERI", "Temperature Excursion Management", date(2026, 7, 28)
        )
        self.assertIsNotNone(hit["record"])
        self.assertTrue(hit["overlap_conflict"])


class TestEvidenceChain(_KestrelTestCase):
    """Evidence hash-chain, tamper detection, Cl.22 isolation, latency, replay."""
    def test_hash_chain_and_tamper_detection(self) -> None:
        """Chain verifies; flipping disposition to DESTROY fails verify_chain."""
        a = self.svc.adjudicate_event("EXC-107133", persist=True)
        tenant = a["result"].tenant_code
        b = self.svc.adjudicate_event("EXC-110287", persist=True)
        if b["result"].tenant_code != tenant:
            for e in self.svc.pack.events:  # type: ignore[union-attr]
                if e["tenant_code"] == tenant and e["event_id"] != "EXC-107133":
                    self.svc.adjudicate_event(e["event_id"], persist=True)
                    break
        chain = self.svc.verify_tenant_chain(tenant)
        self.assertTrue(chain["ok"])
        self.assertGreaterEqual(chain["length"], 1)
        meta = self.svc.store.evidence_for_event("EXC-107133", tenant)[0]
        path = Path(meta["path"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["recommendation"]["disposition"] = "DESTROY"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        broken = self.svc.verify_tenant_chain(tenant)
        self.assertFalse(broken["ok"])
        self.assertTrue(any("tamper" in e or "hash" in e for e in broken["errors"]))

    def test_tenant_isolation_meridian_clause(self) -> None:
        """Foreign tenant cannot read T-KAVERI evidence (PermissionError)."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        bundle_id = out["bundle"]["bundle_id"]
        with self.assertRaises(PermissionError) as ctx:
            self.svc.evidence.get(bundle_id, tenant_code="T-PINNACLE")
        msg = str(ctx.exception).lower()
        self.assertTrue("tenant isolation" in msg or "cl.22" in msg or "belongs" in msg)

    def test_retrieval_latency_under_hour(self) -> None:
        """Full basis retrieval is far under the one-hour board commitment."""
        self.svc.adjudicate_event("EXC-107133", persist=True)
        basis = self.svc.full_basis("EXC-107133", "T-KAVERI")
        self.assertTrue(basis["within_one_hour"])
        self.assertLess(basis["retrieval_latency_ms"], 5_000)
        self.assertTrue(basis["retention_until"])

    def test_replay_determinism(self) -> None:
        """Replaying from bundle yields an identical disposition."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        replay = self.svc.replay_from_bundle(out["bundle"]["bundle_id"], "T-KAVERI")
        self.assertTrue(replay["identical"])


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
            signed = self.svc.lifecycle.sign(
                case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE
            )
        except TransitionError:
            self.svc.lifecycle.transition(case["case_id"], CaseState.RECOMMENDED)
            self.svc.lifecycle.transition(case["case_id"], CaseState.AWAITING_REVIEWER)
            signed = self.svc.lifecycle.sign(
                case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE
            )
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


class TestShadow(_KestrelTestCase):
    """Dr Rao TT-CB-114 shadow bulletin replay."""
    def test_shadow_bulletin_produces_diffs(self) -> None:
        """Shadow replay finds TT-2.14.3 candidates and emits diff rows."""
        report = self.svc.shadow_bulletin()
        self.assertGreater(report["candidates"], 0)
        self.assertTrue("TT-CB-114" in report["change"] or "bulletin" in report["change"].lower())
        self.assertIsInstance(report["diff_rows"], list)


class TestAsOfPack(_KestrelTestCase):
    """In-memory pack as-of SOP helpers and storage-range parsing."""
    def test_kaveri_sop_overlap_on_excursion_date(self) -> None:
        """Pack-level sop_in_force reports overlap and selects highest revision."""
        hit = sop_in_force(
            self.svc.pack.sops,  # type: ignore[union-attr]
            "T-KAVERI",
            "Temperature Excursion Management",
            date(2026, 7, 28),
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.overlap_conflict)
        self.assertGreaterEqual(len(hit.competing), 2)
        self.assertTrue("03" in str(hit.record.get("revision")) or "3" in str(hit.record.get("revision")))

    def test_parse_2_8_variants(self) -> None:
        """parse_storage_range accepts common 2–8 °C and CRT spellings."""
        self.assertEqual(parse_storage_range("2-8 °C"), (2.0, 8.0))
        self.assertEqual(parse_storage_range("+2/+8 C"), (2.0, 8.0))
        self.assertEqual(parse_storage_range("Store at 2–8°C. Do not freeze."), (2.0, 8.0))
        low, high = parse_storage_range("CRT 15-25C")
        self.assertEqual(low, 15.0)
        self.assertEqual(high, 25.0)

    def test_aura_sop_single_rev_on_date(self) -> None:
        """Aura SOP lookup on AUD-2603 date returns a concrete doc_id."""
        hit = sop_in_force(
            self.svc.pack.sops,  # type: ignore[union-attr]
            "T-AURA",
            "Temperature Excursion Management",
            date(2025, 8, 14),
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.record.get("doc_id"))


class TestEngineGolden(_KestrelTestCase):
    """Engine golden / narrative cases beyond EXC-107133."""
    def test_exc_110448_bulletin_underread(self) -> None:
        """TT-2.14.3 under-read applies +1.8 °C bulletin correction."""
        ev = self.svc.pack.event_by_id("EXC-110448")  # type: ignore[union-attr]
        if ev is None:
            self.skipTest("EXC-110448 not in pack")
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertTrue(r.bulletin_applied)
        self.assertIsNotNone(r.corrected_max_temp_c)
        self.assertEqual(r.corrected_max_temp_c, float(ev["max_temp_c"]) + 1.8)

    def test_override_freeze_vaccine_pattern(self) -> None:
        """Below-0 °C adjuvanted vaccine does not RELEASE_WITH_NOTE."""
        ev = self.svc.pack.event_by_id("EXC-110483")  # type: ignore[union-attr]
        if ev is None:
            self.skipTest("EXC-110483 not in pack")
        r = self.svc.engine.adjudicate(ev)  # type: ignore[union-attr]
        self.assertIn(r.recommendation, {DESTROY, ESCALATE, QUARANTINE_PENDING_LAB})

    def test_facility_storm_auto_close(self) -> None:
        """INC-2502 facility-equipment Whitefield rows AUTO_CLOSE."""
        candidates = [
            e
            for e in self.svc.pack.events  # type: ignore[union-attr]
            if e.get("notes")
            and "Whitefield" in str(e.get("notes"))
            and "facility equipment" in str(e.get("triage_outcome") or "").lower()
        ]
        self.assertTrue(candidates, "expected INC-2502 facility rows")
        r = self.svc.engine.adjudicate(candidates[0])  # type: ignore[union-attr]
        self.assertEqual(r.recommendation, AUTO_CLOSE)

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


class TestIdentity(_KestrelTestCase):
    """Product / carrier identity resolution edge cases."""
    def test_gtin_resolves_glucodyne_for_kaveri_or_virent(self) -> None:
        """GTIN 08901234500035 resolves to Glucodyne SoloJet with high confidence."""
        r = IdentityResolver(self.svc.pack)  # type: ignore[arg-type]
        hit = None
        for tenant in ("T-VIRENT", "T-KAVERI", "T-AURA", "T-NORDIA"):
            p = r.resolve_product(tenant, "08901234500035")
            if p.confidence >= 0.9:
                hit = p
                break
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(
            hit.gtin == "08901234500035"
            or (hit.internal_sku and "INS-0119" in hit.internal_sku)
        )

    def test_blank_product_unresolved(self) -> None:
        """Blank product_ref resolves as unresolved with confidence 0."""
        p = IdentityResolver(self.svc.pack).resolve_product("T-VIRENT", "")  # type: ignore[arg-type]
        self.assertEqual(p.confidence, 0.0)
        self.assertEqual(p.match_method, "unresolved")

    def test_tapti_contract_has_no_cold_chain_clause(self) -> None:
        """Tapti Exp Cargo contract has no cold-chain schedule clause."""
        r = IdentityResolver(self.svc.pack)  # type: ignore[arg-type]
        c, err = r.resolve_carrier_contract("Tapti Exp Cargo", date(2026, 7, 28))
        self.assertIsNone(err)
        self.assertIsNotNone(c)
        assert c is not None
        clause = str(c.get("cold_chain_clause"))
        self.assertTrue("none" in clause.lower() or clause.strip() in {"— none —", "—"})


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
            self.assertGreaterEqual(
                r.reg_deadline_utc, ev["_alert_ts"].isoformat(sep=" ")[:19]
            )

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




class TestDeterminism(_KestrelTestCase):
    """Engine determinism: identical inputs yield byte-identical decision hashes."""

    def test_run_twice_byte_identical_decision_hashes(self) -> None:
        """Adjudicate the full pack twice; SHA-256 of decision rows must match."""
        assert self.svc.engine and self.svc.pack

        def _digest() -> str:
            rows = []
            for event in self.svc.pack.events:  # type: ignore[union-attr]
                r = self.svc.engine.adjudicate(event)  # type: ignore[union-attr]
                rows.append(
                    {
                        "event_id": r.event_id,
                        "recommendation": r.recommendation,
                        "confidence": r.confidence,
                        "triage_label": r.triage_label,
                        "corrected_max_temp_c": r.corrected_max_temp_c,
                        "bulletin_applied": r.bulletin_applied,
                        "rationale": list(r.rationale),
                    }
                )
            blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
            return hashlib.sha256(blob.encode("utf-8")).hexdigest()

        h1 = _digest()
        h2 = _digest()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


class TestAgreementAndHealth(_KestrelTestCase):
    """Tests for agreement stratification and health/monitor signals."""

    def test_agreement_report_headline(self) -> None:
        """Agreement command math: 7% of 200 finals, ~49% assistant, distribution intact."""
        report = self.svc.agreement_report()
        self.assertEqual(report["events_total"], 420)
        self.assertEqual(report["events_with_historical_final"], 200)
        self.assertEqual(report["agree_with_historical_final"], 14)
        self.assertEqual(report["agree_with_historical_final_pct"], 7.0)
        self.assertEqual(report["agree_with_assistant"], 206)
        self.assertAlmostEqual(report["agree_with_assistant_pct"], 49.05, places=2)
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


def _run_tests() -> int:
    """Discover and run embedded tests; return 0 on success."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestGoldenExc107133,
        TestAPISmoke,
        TestBitemporalAsOf,
        TestEvidenceChain,
        TestLifecycle,
        TestShadow,
        TestAsOfPack,
        TestEngineGolden,
        TestIdentity,
        TestInvariants,
        TestDeterminism,
        TestAgreementAndHealth,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    # Count checks
    count = suite.countTestCases()
    print(f"Running {count} embedded tests…", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = result.wasSuccessful() and count >= 26
    if count < 26:
        print(f"FAIL: expected ≥26 tests, found {count}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
