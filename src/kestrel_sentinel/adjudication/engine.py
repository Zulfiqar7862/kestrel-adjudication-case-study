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

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional

from kestrel_sentinel.resolution.as_of import parse_storage_range, sop_in_force
from kestrel_sentinel.resolution.identity import IdentityResolver, ResolvedProduct
from kestrel_sentinel.ingest.pack_memory import DataPack
from kestrel_sentinel.resolution.regulatory import regulatory_clock
from kestrel_sentinel.resolution.stability import StabilityResolver, StabilityPosition

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
        d = asdict(self)
        d["rationale"] = " | ".join(self.rationale)
        d["evidence"] = str(self.evidence)
        return d


class AdjudicationEngine:
    def __init__(self, pack: DataPack):
        self.pack = pack
        self.identity = IdentityResolver(pack)
        self.stability = StabilityResolver(pack)
        self.tenants = {t["tenant_code"]: t for t in pack.tenants}

    def adjudicate(self, event: dict[str, Any]) -> AdjudicationResult:
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
    if high is not None and max_t is not None and max_t > high + 1e-9:
        return True
    if low is not None and min_t is not None and min_t < low - 1e-9:
        return True
    return False
