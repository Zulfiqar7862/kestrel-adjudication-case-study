"""AdjudicationService facade that wires store, engine, evidence and lifecycle."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kestrel.closure import closure_counts
from kestrel.config import Settings, get_settings
from kestrel.domain import Disposition
from kestrel.engine import AdjudicationEngine, AdjudicationResult
from kestrel.ingest import DataPack, load_workbook_into_store
from kestrel.lifecycle import CaseLifecycle
from kestrel.shadow import shadow_replay_bulletin
from kestrel.storage.bitemporal import BitemporalStore
from kestrel.storage.evidence import EvidenceStore
from kestrel.utils import parse_datetime

"""Application service: ingest → adjudicate → evidence → case lifecycle."""


log = logging.getLogger(__name__)


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
        self.lifecycle = CaseLifecycle(self.store, self.evidence)
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
                self.lifecycle = CaseLifecycle(self.store, self.evidence)
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
                    reg_deadline_utc=parse_datetime(result.reg_deadline_utc),
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
        for event in events:
            out = self.adjudicate_event(event["event_id"], persist=persist, create_case=persist)
            result: AdjudicationResult = out["result"]
            rows.append(
                {
                    "event_id": result.event_id,
                    "tenant_code": result.tenant_code,
                    "recommendation": result.recommendation,
                    **result.closure_fields(),
                    "bundle_id": (out["bundle"] or {}).get("bundle_id"),
                    "case_id": (out["case"] or {}).get("case_id"),
                    "reg_deadline_utc": result.reg_deadline_utc,
                }
            )
        return {
            "count": len(rows),
            "rows": rows,
            "snapshot_id": self.snapshot_id,
            "closure_counts": closure_counts(rows),
        }

    def _persist(self, result: AdjudicationResult, event: dict[str, Any]) -> dict[str, Any]:
        """Write an evidence bundle for a result and return bundle metadata."""
        assert self.snapshot_id
        assert self.pack
        inputs = {
            "replay": encode_replay({"event": event, "references": self.pack.replay_snapshot(result.tenant_code)}),
            "expected_result": encode_replay(asdict(result)),
            "alert": {
                "event_id": event.get("event_id"),
                "alert_ts_utc": str(event.get("alert_ts_utc")),
                "excursion_start_utc": str(event.get("excursion_start_utc")),
                "temps": {
                    "min": event.get("min_temp_c"),
                    "max": event.get("max_temp_c"),
                    "duration_min": event.get("duration_min"),
                },
                "historical_classification": result.historical_classification,
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
            **result.closure_fields(),
            "requires_human_signature": result.requires_human_signature,
            "confidence": result.confidence,
            "triage_label": result.triage_label,
            "reported_max_temp_c": result.reported_max_temp_c,
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
        """Replay verified bundled inputs with matching versions; compare the full result."""
        doc = self.evidence.get(bundle_id, tenant_code=tenant_code)
        if not self.evidence.verify_document(doc):
            raise ValueError("bundle content hash verification failed")
        if (
            doc.get("rule_pack_version") != self.settings.rule_pack_version
            or doc.get("code_version") != self.settings.code_version
        ):
            raise ValueError("replay requires matching pinned code and rule versions")
        if "replay" not in doc["inputs"]:
            raise ValueError("legacy bundle has no immutable replay inputs")
        saved = decode_replay(doc["inputs"]["replay"])
        replay_pack = DataPack(path=Path("bundled-inputs"), **saved["references"])
        again = AdjudicationEngine(replay_pack).adjudicate(saved["event"])
        original = doc["recommendation"]["disposition"]
        return {
            "bundle_id": bundle_id,
            "original_disposition": original,
            "replay_disposition": again.recommendation,
            "identical": doc["inputs"].get("expected_result") == encode_replay(asdict(again)),
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

    def as_of_sop(
        self, tenant_code: str, as_of_date: str, title: str = "Temperature Excursion Management"
    ) -> dict[str, Any]:
        """Look up SOP-in-force for tenant/title on an ISO date string."""
        as_of_day = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        return self.store.sop_in_force(tenant_code, title, as_of_day)

    def agreement_report(self) -> dict[str, Any]:
        """Stratify engine vs historical final / assistant agreement across the pack.

        Agreement with ``final_disposition`` is computed on the 200 rows that have a
        non-empty historical final (the human-opened stratum). Assistant agreement
        uses ``rules_engine_recommendation`` across all 420 rows (pack README: that
        column is the LLM assistant draft since 2024).
        """
        assert self.engine and self.pack
        closure_rows = []
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
        started = time.perf_counter()
        for event in self.pack.events:
            result = self.engine.adjudicate(event)
            closure_rows.append({"recommendation": result.recommendation, **result.closure_fields()})
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
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "events_total": n_all,
            "closure_counts": closure_counts(closure_rows),
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
                "Historical-final agreement uses the 200 non-empty final_disposition rows (case_opened stratum), not all 420.",
                "Historical agreement is a comparison, not a safety measure; unresolved evidence can route to QA.",
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
            # Reproduced 0.4.3 sample regression baseline, NOT QA-approved clinical policy.
            baseline_mix = {
                "AUTO_CLOSE": 0,
                "HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED": 130,
                "ESCALATED_TO_SENIOR_QA": 290,
                "RELEASE_WITH_NOTE": 0,
                "DESTROY": 0,
                "QUARANTINE_PENDING_LAB": 0,
            }
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        closure_rows = []
        mix: Counter[str] = Counter()
        deadline_breached = 0
        deadline_at_risk = 0
        reportable = 0
        queue_ages_hours: list[float] = []
        firmware_counts: Counter[str] = Counter()
        for event in self.pack.events:
            result = self.engine.adjudicate(event)
            closure_rows.append({"recommendation": result.recommendation, **result.closure_fields()})
            mix[result.recommendation] += 1
            firmware_counts[str(event.get("logger_fw") or "unknown")] += 1
            if result.regulator_reportable:
                reportable += 1
                # Pack historical late filings (reported_within_window = N)
                if str(event.get("reported_within_window") or "").upper() in {"N", "NO", "FALSE", "0"}:
                    deadline_breached += 1
                # Prototype at-risk: open reportable cases whose deadline is within 6h
                # of "now" relative to alert+window (cannot truly page from static pack).
                deadline = parse_datetime(result.reg_deadline_utc)
                alert_ts = event.get("_alert_ts") or parse_datetime(str(event.get("alert_ts_utc") or ""))
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
                verification = self.evidence.verify_chain(tenant)
            except Exception as exc:  # noqa: BLE001 — health must not crash
                verification = {"ok": False, "error": str(exc)}
            chain_results[tenant] = verification
            if verification.get("ok") is False and verification.get("length", 0) not in (0, None):
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
        pack_age_hours = (datetime.now() - pack_mtime).total_seconds() / 3600.0 if pack_mtime else None

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
            {
                "pack_path": str(pack_path),
                "pack_age_hours": None if pack_age_hours is None else round(pack_age_hours, 2),
            },
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
            "Enable storm brake; route unverified historical facility/duplicate candidates to human review; drain by reg_deadline_utc ASC.",
            max_queue_age > 12,
        )
        bulletin_fw = "TT-2.14.3"
        _alert(
            "firmware_bulletin_change",
            "P2",
            {
                "watched_firmware": bulletin_fw,
                "events_on_fw": firmware_counts.get(bulletin_fw, 0),
                "firmware_histogram": dict(firmware_counts),
            },
            "vendor bulletin hash/version changes vs last approved ref_snapshot",
            "Platform on-call + Marieke de Vries notified on version change (Aurastat ask)",
            "Run shadow-bulletin; open Dr Rao gate; re-adjudicate affected firmware cohort; withdraw carrier invoices if liability flips (INC-2506).",
            False,  # static pack: no live bulletin feed; hook is ready
        )

        return {
            "ok": not any(
                alert["firing"] and alert["severity"] == "P1"
                for alert in alerts
                if alert["name"] != "regulatory_deadline_breached"
            ),
            "generated_at_utc": now.isoformat(sep=" "),
            "decision_mix": dict(sorted(mix.items())),
            "closure_counts": closure_counts(closure_rows),
            "baseline_mix": baseline_mix,
            "reportable_in_pack": reportable,
            "deadline_breached_in_pack": deadline_breached,
            "deadline_at_risk_pattern_rows": deadline_at_risk,
            "chain_verification": chain_results,
            "alerts": alerts,
            "note": "Pack is stratified historical data; breached/at-risk counts here demonstrate the monitor against known INC/late rows, not live pages.",
        }


def encode_replay(value: Any) -> Any:
    """JSON-safe tagged serialization; do not guess dates from ordinary strings."""
    if isinstance(value, datetime):
        return {"__kestrel_datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__kestrel_date__": value.isoformat()}
    if isinstance(value, dict):
        return {k: encode_replay(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode_replay(v) for v in value]
    return value


def decode_replay(value: Any) -> Any:
    """Restore tagged reference/event values from a verified bundle."""
    if isinstance(value, dict):
        if set(value) == {"__kestrel_datetime__"}:
            return datetime.fromisoformat(value["__kestrel_datetime__"])
        if set(value) == {"__kestrel_date__"}:
            return date.fromisoformat(value["__kestrel_date__"])
        return {k: decode_replay(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_replay(v) for v in value]
    return value
