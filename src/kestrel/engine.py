"""Pure, deterministic adjudication engine: no I/O, no LLM, no randomness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from kestrel.decision_rules import (
    AUTO_CLOSE,
    DESTROY,
    ESCALATE,
    HISTORICAL_CANDIDATE,
    QUARANTINE_PENDING_LAB,
    RELEASE,
    RELEASE_WITH_NOTE,
    RETURN_TO_ORIGIN,
    REWORK_RELABEL,
    ExcursionFacts,
    decide,
)
from kestrel.ingest import DataPack
from kestrel.rules.as_of import StorageLimits, parse_storage_limits, sop_in_force
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
    HISTORICAL_CANDIDATE,
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
    identity_evidence: dict[str, Any] = field(default_factory=dict)
    study_discovery: dict[str, Any] = field(default_factory=dict)
    historical_classification: Optional[str] = None
    closure_eligibility: str = "not_eligible"
    independent_closure_evidence: list[str] = field(default_factory=list)
    requires_human_review: bool = True
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
    reported_max_temp_c: Optional[float] = None
    bulletin_applied: bool = False
    regulator_reportable: Optional[bool] = None
    reg_window_hours: Optional[float] = None
    reg_deadline_utc: Optional[str] = None
    historical_recommendation: Optional[str] = None
    historical_final_disposition: Optional[str] = None
    agrees_with_historical_final: Optional[bool] = None
    agrees_with_historical_engine: Optional[bool] = None

    def closure_fields(self) -> dict[str, Any]:
        """One assessment shared by API, CLI, batch metrics and sealed evidence."""
        return {
            "historical_classification": self.historical_classification,
            "closure_eligibility": self.closure_eligibility,
            "independent_closure_evidence": list(self.independent_closure_evidence),
            "requires_human_review": self.requires_human_review,
        }

    def to_row(self) -> dict[str, Any]:
        """Flatten the result into a CSV/JSON-friendly dict row."""
        row = asdict(self)
        row["rationale"] = " | ".join(self.rationale)
        row["evidence"] = str(self.evidence)
        return row


class AdjudicationEngine:
    """Deterministic as-of adjudication engine over a DataPack."""

    def __init__(
        self, pack: DataPack, *, bulletin_bound_c: float = BULLETIN_BIAS_C, bulletin_firmware: str = BULLETIN_FW
    ) -> None:
        """Bind identity/stability resolvers to the pack."""
        self.pack = pack
        if bulletin_bound_c < 0:
            raise ValueError("bulletin bound must be non-negative")
        self.bulletin_bound_c = bulletin_bound_c
        self.bulletin_firmware = bulletin_firmware
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

        # TT-CB-114 supplies an upper bound, not a calibrated measurement.
        max_temp = to_float(event.get("max_temp_c"))
        min_temp = to_float(event.get("min_temp_c"))
        duration_min = to_float(event.get("duration_min")) or 0.0
        bulletin = str(event.get("logger_fw") or "") == self.bulletin_firmware
        corrected_max = max_temp  # legacy internal facts name: scenario, never measured correction
        evidence["temps"] = {
            "min_reported": min_temp,
            "max_reported": max_temp,
            "mean_reported": to_float(event.get("mean_temp_c")),
            "duration_min": duration_min,
            "bulletin_tt_cb_114": bulletin,
        }

        # --- identity ---
        product = self.identity.resolve_product(tenant, event.get("product_ref_as_received"), as_of=as_of)
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
        evidence["product"].update(product.assessment())
        evidence["identity"] = {"product": product.assessment()}
        evidence["identity"]["facility"] = {
            "status": "UNRESOLVED_NOT_EVALUATED",
            "usage": "UNUSED_NOT_AUTHORITY_INPUT",
            "reasons": [
                "Facility resolver unused by engine/SOP selection; tenant ownership and governing site authority not established"
            ],
            "links": [],
            "candidates": [],
            "release_identity_eligible": False,
        }
        if product.confidence < 0.5:
            rationale.append(f"Product identity weak ({product.match_method}): {product.unresolved_reason}")

        # --- labelled range ---
        spec_text = product.storage_spec_text or event.get("spec_text_as_received")
        limits = parse_storage_limits(spec_text)
        low = limits.lower.value_c if limits.lower else None
        high = limits.upper.value_c if limits.upper else None
        evidence["labelled_range"] = {"text": spec_text, "low_c": low, "high_c": high, **limits.as_dict()}
        evidence["labelled_range"]["constraints_status"] = "retained, not independently verified"

        # --- stability as cited ---
        stability_position = self.stability.resolve(product)
        evidence["stability"] = {
            "study_ref": stability_position.study_ref,
            "permitted_text": stability_position.permitted_text,
            "source": stability_position.source,
            "authority_issue": stability_position.authority_issue,
            "readable": stability_position.readable,
            "notes": stability_position.notes,
            "presentation_mismatch_risk": stability_position.presentation_mismatch_risk,
            "cumulative_assessment": (
                "unresolved: verified batch identity and complete prior-exposure history unavailable"
                if stability_position.cumulative or stability_position.cumulative_above_label
                else "unresolved: study applicability not established; cumulative requirement unknown"
                if stability_position.authority_issue
                else "not cumulative per selected study"
            ),
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
                    f"effective on {as_of}; candidate {sop_rev} (highest rev, not governing authority). "
                    "Human must confirm (override EXC-110490 pattern)."
                )
        else:
            evidence["sop"] = None
            rationale.append(f"No Temperature Excursion Management SOP in force for {tenant} on {as_of}")

        # The workbook is an index, not the SOP body or its site annexure. A
        # filename/section pointer cannot establish the governing acceptance limits.
        sop_authority_issue = (
            "governing SOP missing"
            if not sop_hit
            else "SOP/site acceptance authority unresolved: indexed body/annexure content not supplied"
        )
        evidence["sop_authority"] = {"status": "unresolved", "reason": sop_authority_issue}

        # Study discovery is exhaustive within the tenant, not a guessed alternate citation.
        # Snapshot membership is not a historical knowledge-time proof.
        discovery = self.stability.discover(
            product,
            event_date=as_of,
            knowledge_date=alert_ts.date() if alert_ts else None,
            min_temp_c=min_temp,
            max_temp_c=max_temp + (self.bulletin_bound_c if bulletin else 0) if max_temp is not None else None,
            duration_min=to_float(event.get("duration_min")),
            sop_authority="CONFLICT" if sop_overlap else "UNKNOWN",
        ).assessment()
        evidence["stability"]["discovery"] = discovery
        if discovery["selected_study_ref"] is None:
            stability_position.source = "unresolved"
            stability_position.authority_issue = (
                stability_position.authority_issue or "No admissible study: see typed candidate rejection reasons"
            )
            evidence["stability"]["source"] = "unresolved"
            evidence["stability"]["authority_issue"] = stability_position.authority_issue
            if not (stability_position.cumulative or stability_position.cumulative_above_label):
                evidence["stability"]["cumulative_assessment"] = (
                    "unresolved: no admissible study; cumulative requirement unknown"
                )
            rationale.append("Study discovery unresolved; candidate rejection catalogue retained in evidence")
            rationale.extend(
                f"Study {candidate['study_ref']}: {reason['code']} [{reason['assessment']}] — {reason['detail']}"
                for candidate in discovery["candidates"]
                if candidate["cited"]
                for reason in candidate["rejections"]
            )

        # --- carrier contract as-at ---
        carrier_identity = self.identity.resolve_carrier(tenant, event.get("carrier_ref_as_received"), as_of)
        carrier, carrier_err = carrier_identity.record, "; ".join(carrier_identity.reasons) or None
        evidence["identity"]["carrier"] = carrier_identity.assessment()
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
            "reportability_status": clock.reportability_status,
            "deadline_status": clock.deadline_status,
            "historical_window_reference": clock.historical_window_reference,
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
            sop_authority_issue=sop_authority_issue,
            storage_limits=limits,
        )
        rationale.extend(extra)
        evidence["decision"] = {
            "rule": next(line.removeprefix("Decision rule: ") for line in extra if line.startswith("Decision rule: ")),
            "limitations": [
                line
                for line in extra
                if line.startswith(
                    ("AUTO_CLOSE limitation:", "Historical closure limitation:", "Additional storage constraints")
                )
            ],
        }
        if bulletin:
            upper_max = max_temp + self.bulletin_bound_c if max_temp is not None else None
            upper_min = min_temp + self.bulletin_bound_c if min_temp is not None else None
            upper_event = dict(event)
            for key in ("min_temp_c", "max_temp_c", "mean_temp_c"):
                value = to_float(event.get(key))
                if value is not None:
                    upper_event[key] = value + self.bulletin_bound_c
            upper = self._decide(
                event=upper_event,
                product=product,
                stability_position=stability_position,
                low=low,
                high=high,
                corrected_max=upper_max,
                min_temp=upper_min,
                duration_min=duration_min,
                sop_overlap=sop_overlap,
                sop_authority_issue=sop_authority_issue,
                storage_limits=limits,
            )
            sensitive = recommendation != upper[0]
            evidence["temps"]["uncertainty"] = {
                "source": "TT-CB-114",
                "firmware": self.bulletin_firmware,
                "offset_interval_c": [0.0, self.bulletin_bound_c],
                "model": "two endpoint scenarios shifting supplied summaries; not a raw-series proof",
                "reported_scenario": {
                    "min_c": min_temp,
                    "max_c": max_temp,
                    "mean_c": to_float(event.get("mean_temp_c")),
                    "recommendation": recommendation,
                    "reasoning": extra,
                },
                "upper_bound_scenario": {
                    "min_c": upper_min,
                    "max_c": upper_max,
                    "mean_c": upper_event.get("mean_temp_c"),
                    "recommendation": upper[0],
                    "reasoning": upper[3],
                },
                "outcome_sensitive": sensitive,
            }
            rationale.append(
                f"TT-CB-114: reported and upper-bound (+{self.bulletin_bound_c}°C) scenarios; "
                "reported observations unchanged; endpoint analysis is not full-series validation"
            )
            if sensitive:
                rationale.append(
                    f"Temperature uncertainty changes disposition: {recommendation} vs {upper[0]}; QA review required"
                )
                recommendation, triage, conf = ESCALATE, "temperature_uncertainty", min(conf, upper[2], 0.4)
                evidence["decision"] = {"rule": "temperature_uncertainty_gate", "limitations": []}

        if recommendation in {RELEASE, RELEASE_WITH_NOTE, AUTO_CLOSE} and (not product.release_identity_eligible):
            recommendation, triage, conf = ESCALATE, "unresolved_typed_identity", 0.0
            rationale.append("Identity unresolved: tenant product evidence cannot authorize release or closure")
            evidence["decision"] = {"rule": "typed_identity_release_gate", "limitations": []}

        if not product.release_identity_eligible and evidence["decision"]["rule"] != "typed_identity_release_gate":
            prior_rule = evidence["decision"]["rule"]
            recommendation, triage, conf = ESCALATE, "unresolved_typed_product_identity", 0.0
            rationale.append(
                "Product identity unresolved: historical classification remains reference only; QA must resolve identity"
            )
            evidence["decision"] = {
                "rule": "typed_identity_unresolved_gate",
                "prior_rule": prior_rule,
                "limitations": [],
            }

        if not any(p.get("tenant_code") == tenant for p in self.pack.products):
            recommendation, triage, conf = ESCALATE, "unresolved_tenant_identity", 0.0
            rationale.append("Unknown tenant has no product reference pool; no cross-tenant fallback")
            evidence["decision"] = {"rule": "unresolved_tenant_identity_gate", "limitations": []}

        requires_human = recommendation != AUTO_CLOSE
        # Dr Rao: automation on closures only. Even high-confidence RELEASE requires sign-off.
        if recommendation in ACTIONABLE_DISPOSITIONS:
            requires_human = True

        historical_classification = event.get("triage_outcome")
        closure_eligibility = (
            "historical_candidate_unverified"
            if recommendation == HISTORICAL_CANDIDATE
            else "rule_supported_unverified"
            if recommendation == AUTO_CLOSE
            else "not_eligible"
        )
        # Workbook classifications, reviewer-queue derivatives and incident prose
        # supply no independently authenticated duplicate/load verification record.
        # Do not consume invented `*_verified` event flags as verification.
        evidence["closure_assessment"] = {
            "historical_classification": historical_classification,
            "classification_source": "01_Excursion_Events.triage_outcome (historical reference only)",
            "closure_eligibility": closure_eligibility,
            "independent_closure_evidence": [],
            "requires_human_review": requires_human,
            "limitation": "No independent duplicate/load verification artifact supplied; rule support is not independent verification",
        }
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
            identity_evidence=evidence["identity"],
            study_discovery=discovery,
            historical_classification=historical_classification,
            closure_eligibility=closure_eligibility,
            independent_closure_evidence=[],
            requires_human_review=requires_human,
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
            reported_max_temp_c=corrected_max,
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
        sop_authority_issue: Optional[str],
        storage_limits: StorageLimits,
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
            sop_authority_issue=sop_authority_issue,
            storage_limits=storage_limits,
        )
        verdict, trace = decide(facts)
        return verdict.disposition, verdict.triage_label, verdict.confidence, trace
