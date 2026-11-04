"""SQLite bitemporal reference store.

valid_from / valid_to  = when true in the world (SOP effective dates, contract term)
tx_from / tx_to        = when Sentinel believed it (ingestion / correction)
"""

from __future__ import annotations

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
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(d: date | datetime | None) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.isoformat(sep=" ")
    return d.isoformat()


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
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
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
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
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def set_meta(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
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
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alert WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["payload_json"])

    def list_alerts(self, tenant_code: Optional[str] = None) -> list[dict[str, Any]]:
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
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_index WHERE event_id=? AND tenant_code=? ORDER BY created_at",
                (event_id, tenant_code),
            ).fetchall()
        return [dict(r) for r in rows]

    def chain_for_tenant(self, tenant_code: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_index WHERE tenant_code=? ORDER BY created_at, bundle_id",
                (tenant_code,),
            ).fetchall()
        return [dict(r) for r in rows]
