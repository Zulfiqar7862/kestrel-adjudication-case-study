"""Load the KCCS Sentinel Reference Data Pack workbook into memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook


def _parse_dt(value: Any) -> Optional[datetime]:
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
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _rows(ws) -> list[dict[str, Any]]:
    headers = [c.value for c in ws[1]]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None and all(v is None for v in row):
            continue
        out.append({headers[i]: row[i] for i in range(len(headers))})
    return out


@dataclass
class DataPack:
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
        for e in self.events:
            if e.get("event_id") == event_id:
                return e
        return None
