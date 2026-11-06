"""Reads the Sentinel reference workbook and loads it into the bitemporal store."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from openpyxl import load_workbook

from kestrel.utils import parse_date, parse_datetime, sheet_rows

if TYPE_CHECKING:
    from kestrel.storage.bitemporal import BitemporalStore


"""Load the KCCS Sentinel Reference Data Pack workbook into memory."""


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
    def load(cls, path: Path | str) -> DataPack:
        """Load all relevant sheets from the Excel pack into a DataPack."""
        path = Path(path)
        workbook = load_workbook(path, data_only=True, read_only=True)
        pack = cls(path=path)
        pack.events = sheet_rows(workbook["01_Excursion_Events"])
        pack.products = sheet_rows(workbook["02_Product_Master"])
        pack.facilities = sheet_rows(workbook["03_Facility_Registry"])
        pack.carriers = sheet_rows(workbook["04_Carrier_Contracts"])
        pack.sops = sheet_rows(workbook["05_SOP_Index"])
        pack.stability = sheet_rows(workbook["06_Stability_Index"])
        pack.aliases = sheet_rows(workbook["07_Alias_Observations"])
        pack.overrides = sheet_rows(workbook["09_Override_Reasons"])
        pack.tenants = [
            row
            for row in sheet_rows(workbook["12_Tenant_Constraints"])
            if row.get("tenant_code") and str(row["tenant_code"]).startswith("T-")
        ]
        pack.incidents = sheet_rows(workbook["14_Incident_Log"])
        workbook.close()
        # Normalize a few fields used heavily
        for event in pack.events:
            event["_alert_ts"] = parse_datetime(event.get("alert_ts_utc"))
            event["_excursion_start"] = parse_datetime(event.get("excursion_start_utc"))
            event["_excursion_end"] = parse_datetime(event.get("excursion_end_utc"))
        for sop in pack.sops:
            sop["_effective_from"] = parse_date(sop.get("effective_from"))
            sop["_effective_to"] = parse_date(sop.get("effective_to"))
        for contract in pack.carriers:
            contract["_effective_from"] = parse_date(contract.get("effective_from"))
            effective_to = contract.get("effective_to")
            if effective_to is None or str(effective_to).lower() in {"evergreen", ""}:
                contract["_effective_to"] = None
            else:
                contract["_effective_to"] = parse_date(effective_to)
        return pack

    def event_by_id(self, event_id: str) -> Optional[dict[str, Any]]:
        """Return the excursion event dict for event_id, or None."""
        for event in self.events:
            if event.get("event_id") == event_id:
                return event
        return None


"""Workbook loader adapter — loads the real pack into the bitemporal store."""


log = logging.getLogger(__name__)


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
    workbook = load_workbook(pack_path, data_only=True, read_only=True)

    # Products
    for product in sheet_rows(workbook["02_Product_Master"]):
        tenant = product.get("tenant_code")
        key = str(product.get("gtin") or product.get("internal_sku") or product.get("brand_as_labelled") or id(product))
        store.insert_ref(
            entity_type="product",
            tenant_code=tenant,
            natural_key=f"{tenant}:{key}",
            payload=product,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system=str(product.get("erp_source") or "ERP"),
        )

    # SOPs — each revision is a valid-time version
    for sop in sheet_rows(workbook["05_SOP_Index"]):
        effective_from = parse_date(sop.get("effective_from")) or date(2020, 1, 1)
        effective_to = parse_date(sop.get("effective_to"))
        store.insert_ref(
            entity_type="sop",
            tenant_code=sop.get("tenant_code"),
            natural_key=f"{sop.get('doc_id')}:{sop.get('revision')}",
            payload=sop,
            valid_from=effective_from,
            valid_to=effective_to,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-07",
        )

    # Stability
    for sop in sheet_rows(workbook["06_Stability_Index"]):
        store.insert_ref(
            entity_type="stability",
            tenant_code=sop.get("tenant_code"),
            natural_key=str(sop.get("study_ref")),
            payload=sop,
            valid_from=date(2020, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-06",
        )

    # Carriers
    for contract in sheet_rows(workbook["04_Carrier_Contracts"]):
        effective_from = parse_date(contract.get("effective_from")) or date(2019, 1, 1)
        to_raw = contract.get("effective_to")
        effective_to = None if to_raw is None or str(to_raw).lower() == "evergreen" else parse_date(to_raw)
        store.insert_ref(
            entity_type="carrier_contract",
            tenant_code=None,
            natural_key=str(contract.get("contract_id")),
            payload=contract,
            valid_from=effective_from,
            valid_to=effective_to,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="SYS-08",
        )

    # Aliases
    for alias in sheet_rows(workbook["07_Alias_Observations"]):
        store.insert_ref(
            entity_type="alias",
            tenant_code=None,
            natural_key=f"{alias.get('entity_kind')}:{alias.get('string_a')}:{alias.get('string_b')}",
            payload=alias,
            valid_from=parse_date(alias.get("confirmed_on")) or date(2025, 1, 1),
            valid_to=None,
            tx_from=tx_from,
            snapshot_id=snapshot_id,
            source_system="reviewer",
        )

    # Tenants
    for t in sheet_rows(workbook["12_Tenant_Constraints"]):
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
    count = 0
    for event in sheet_rows(workbook["01_Excursion_Events"]):
        eid = event.get("event_id")
        if not eid:
            continue
        event = dict(event)
        event["_alert_ts"] = parse_datetime(event.get("alert_ts_utc"))
        event["_excursion_start"] = parse_datetime(event.get("excursion_start_utc"))
        event["_excursion_end"] = parse_datetime(event.get("excursion_end_utc"))
        # serialize datetimes for JSON
        payload = {k: (v.isoformat(sep=" ") if isinstance(v, datetime) else v) for k, v in event.items()}
        payload["_alert_ts"] = event["_alert_ts"].isoformat(sep=" ") if event["_alert_ts"] else None
        payload["_excursion_start"] = (
            event["_excursion_start"].isoformat(sep=" ") if event["_excursion_start"] else None
        )
        store.upsert_alert(str(eid), str(event.get("tenant_code") or ""), payload, snapshot_id)
        count += 1

    workbook.close()
    store.set_meta("ref_snapshot_id", snapshot_id)
    store.set_meta("pack_path", str(pack_path))
    store.set_meta("loaded_alerts", str(count))
    log.info("loaded workbook", extra={"extra_fields": {"snapshot_id": snapshot_id, "alerts": count}})
    return snapshot_id
