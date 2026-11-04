"""Workbook loader adapter — loads the real pack into the bitemporal store."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from openpyxl import load_workbook

from kestrel_sentinel.store.bitemporal import BitemporalStore

log = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
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
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _rows(ws) -> list[dict[str, Any]]:
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
