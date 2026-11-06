"""Pure, deterministic adjudication engine: no I/O, no LLM, no randomness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from kestrel.decision_rules import (
    AUTO_CLOSE,
    DESTROY,
    ESCALATE,
    QUARANTINE_PENDING_LAB,
    RELEASE,
    RELEASE_WITH_NOTE,
    RETURN_TO_ORIGIN,
    REWORK_RELABEL,
    ExcursionFacts,
    decide,
)
from kestrel.ingest import DataPack
from kestrel.rules.as_of import parse_storage_range, sop_in_force
from kestrel.rules.identity import IdentityResolver, ResolvedProduct
from kestrel.rules.regulatory import regulatory_clock
from kestrel.rules.stability import StabilityPosition, StabilityResolver
from kestrel.utils import to_float

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


BULLETIN_FW = "TT-2.14.3"


BULLETIN_BIAS_C = 1.8


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
        row = asdict(self)
        row["rationale"] = " | ".join(self.rationale)
        row["evidence"] = str(self.evidence)
        return row


class AdjudicationEngine:
    """Deterministic as-of adjudication engine over a DataPack."""

    def __init__(self, pack: DataPack) -> None:
        """Bind identity/stability resolvers to the pack."""
        self.pack = pack
        self.identity = IdentityResolver(pack)
        self.stability = StabilityResolver(pack)
        self.tenants = {tenant["tenant_code"]: tenant for tenant in pack.tenants}

    def adjudicate(self, event: dict[str, Any]) -> AdjudicationResult:
        """Adjudicate one excursion event dict into an AdjudicationResult."""
        event_id = str(event.get("event_id"))
        tenant = str(event.get("tenant_code") or "")
        rationale: list[str] = []
        evidence: dict[str, Any] = {"event_id": event_id, "tenant_code": tenant}

        alert_ts: Optional[datetime] = event.get("_alert_ts")
        as_of = (event.get("_excursion_start") or alert_ts or datetime.utcnow()).date()

        # --- sensor bulletin correction ---
        max_temp = to_float(event.get("max_temp_c"))
        min_temp = to_float(event.get("min_temp_c"))
        duration_min = to_float(event.get("duration_min")) or 0.0
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
            rationale.append(f"Product identity weak ({product.match_method}): {product.unresolved_reason}")

        # --- labelled range ---
        spec_text = product.storage_spec_text or event.get("spec_text_as_received")
        low, high = parse_storage_range(spec_text)
        evidence["labelled_range"] = {"text": spec_text, "low_c": low, "high_c": high}

        # --- stability as cited ---
        stability_position = self.stability.resolve(product)
        evidence["stability"] = {
            "study_ref": stability_position.study_ref,
            "permitted_text": stability_position.permitted_text,
            "source": stability_position.source,
            "readable": stability_position.readable,
            "notes": stability_position.notes,
            "presentation_mismatch_risk": stability_position.presentation_mismatch_risk,
        }
        rationale.extend(stability_position.notes)

        # --- SOP as-at excursion date ---
        sop_hit = sop_in_force(self.pack.sops, tenant, "Temperature Excursion Management", as_of)
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
                "competing_revisions": [competitor.get("revision") for competitor in sop_hit.competing],
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
        carrier, carrier_err = self.identity.resolve_carrier_contract(event.get("carrier_ref_as_received"), as_of)
        has_cold_chain_clause = None
        carrier_id = None
        if carrier:
            carrier_id = carrier.get("contract_id")
            clause = str(carrier.get("cold_chain_clause") or "")
            has_cold_chain_clause = "none" not in clause.lower() and clause.strip() not in {"", "—", "-"}
            evidence["carrier"] = {
                "contract_id": carrier_id,
                "legal_entity": carrier.get("counterparty_legal_entity"),
                "cold_chain_clause": clause,
                "claim_window_days": carrier.get("claim_window_days"),
            }
            if not has_cold_chain_clause:
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
            stability_position=stability_position,
            low=low,
            high=high,
            corrected_max=corrected_max,
            min_temp=min_temp,
            duration_min=duration_min,
            sop_overlap=sop_overlap,
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
            stability_study_ref=stability_position.study_ref,
            sop_doc_id=str(sop_doc) if sop_doc else None,
            sop_revision=str(sop_rev) if sop_rev else None,
            sop_overlap_conflict=sop_overlap,
            carrier_contract_id=str(carrier_id) if carrier_id else None,
            carrier_has_cold_chain_clause=has_cold_chain_clause,
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
        stability_position: StabilityPosition,
        low: Optional[float],
        high: Optional[float],
        corrected_max: Optional[float],
        min_temp: Optional[float],
        duration_min: float,
        sop_overlap: bool,
    ) -> tuple[str, str, float, list[str]]:
        """Build the facts for this alert and run the ordered rule chain (see decision_rules)."""
        facts = ExcursionFacts(
            event=event,
            product=product,
            stability=stability_position,
            label_low_c=low,
            label_high_c=high,
            corrected_max_c=corrected_max,
            min_c=min_temp,
            duration_min=duration_min,
            sop_overlap=sop_overlap,
        )
        verdict, trace = decide(facts)
        return verdict.disposition, verdict.triage_label, verdict.confidence, trace
