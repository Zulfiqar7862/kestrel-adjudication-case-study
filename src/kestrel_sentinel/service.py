"""Application service: ingest → adjudicate → evidence → case lifecycle."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from kestrel_sentinel.adjudication.engine import AdjudicationEngine, AdjudicationResult
from kestrel_sentinel.config import Settings, get_settings
from kestrel_sentinel.domain.enums import Disposition
from kestrel_sentinel.evidence.store import EvidenceStore
from kestrel_sentinel.ingest.pack_memory import DataPack
from kestrel_sentinel.ingest.workbook import load_workbook_into_store
from kestrel_sentinel.lifecycle.machine import CaseLifecycle
from kestrel_sentinel.shadow.replay import shadow_replay_bulletin
from kestrel_sentinel.store.bitemporal import BitemporalStore

log = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
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


class AdjudicationService:
    def __init__(self, settings: Optional[Settings] = None):
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
        return self.evidence.produce_full_basis(event_id, tenant_code)

    def verify_tenant_chain(self, tenant_code: str) -> dict[str, Any]:
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
        assert self.engine and self.pack
        return shadow_replay_bulletin(self.pack, self.engine)

    def as_of_sop(self, tenant_code: str, as_of_date: str, title: str = "Temperature Excursion Management"):
        from datetime import date as date_cls

        d = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        return self.store.sop_in_force(tenant_code, title, d)
