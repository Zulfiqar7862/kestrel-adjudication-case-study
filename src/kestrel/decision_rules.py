"""Disposition rules, one small function per rule, applied in a fixed order.

How it works
------------
``decide()`` walks ``DECISION_RULES`` from top to bottom. Each rule looks at the
``ExcursionFacts`` for one alert and either

* returns a ``Verdict`` (the first verdict wins and the walk stops), or
* returns ``None`` and lets the next rule run.

Any rule may add a plain-English line to ``trace``; that list becomes the
"why this recommendation" rationale a reviewer sees. Order matters and is part of
the rule pack version: cheap non-actionable triages first, then hard escalations,
then temperature and stability arithmetic, then a conservative fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, NamedTuple, Optional

from kestrel.rules.identity import ResolvedProduct
from kestrel.rules.stability import StabilityPosition
from kestrel.utils import to_float

AUTO_CLOSE = "AUTO_CLOSE"
RELEASE = "RELEASE"
RELEASE_WITH_NOTE = "RELEASE_WITH_NOTE"
QUARANTINE_PENDING_LAB = "QUARANTINE_PENDING_LAB"
DESTROY = "DESTROY"
RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"
REWORK_RELABEL = "REWORK_RELABEL"
ESCALATE = "ESCALATED_TO_SENIOR_QA"

# Thresholds named so every number in a rule has a meaning.
EPSILON = 1e-9
MIN_PRODUCT_CONFIDENCE = 0.5
GAP_MIN_MINUTES = 30
GAP_SHARE_OF_EXCURSION = 0.5
SENSOR_ARTEFACT_TOLERANCE_C = 0.5
DOCK_DOOR_MAX_MINUTES = 20
DOCK_DOOR_TOLERANCE_C = 5
COLD_CHAIN_MAX_LABEL_C = 8
ULTRA_COLD_LABEL_C = -60
ULTRA_COLD_TOP_UP_MINUTES = 5
BRIEF_BREACH_HOURS = 0.25
BRIEF_BREACH_TOLERANCE_C = 2
SEVERE_BREACH_MARGIN_C = 5
MILD_EXCURSION_HOURS = 0.5
MILD_EXCURSION_TOLERANCE_C = 3
REPEAT_LANE_EXCURSIONS = 3


class Verdict(NamedTuple):
    """The outcome of the first rule that decides."""

    disposition: str
    triage_label: str
    confidence: float


@dataclass(frozen=True)
class ExcursionFacts:
    """Everything the rules need about one alert, already resolved as-of its date."""

    event: dict[str, Any]
    product: ResolvedProduct
    stability: StabilityPosition
    label_low_c: Optional[float]
    label_high_c: Optional[float]
    corrected_max_c: Optional[float]
    min_c: Optional[float]
    duration_min: float
    sop_overlap: bool
    sop_authority_issue: Optional[str] = "governing SOP/site authority not established"

    @property
    def duration_h(self) -> float:
        return self.duration_min / 60.0

    @property
    def gateway_gap_min(self) -> float:
        return to_float(self.event.get("gateway_gap_min")) or 0.0

    @property
    def interpolated(self) -> bool:
        return _flag(self.event.get("interpolated"))

    @property
    def dock_door_open(self) -> bool:
        return _flag(self.event.get("dock_door_open_flag"))

    @property
    def prior_lane_excursions(self) -> int:
        return int(self.event.get("prior_excursions_lane_90d") or 0)

    @property
    def triage(self) -> str:
        """Historical triage text, lower-cased for matching."""
        return str(self.event.get("triage_outcome") or "").lower()

    @property
    def out_of_label_range(self) -> Optional[bool]:
        return is_out_of_range(self.corrected_max_c, self.min_c, self.label_low_c, self.label_high_c)

    def max_within(self, limit_c: Optional[float], tolerance_c: float) -> bool:
        """True when the corrected peak is known and at most ``limit_c + tolerance_c``."""
        return (
            limit_c is not None and self.corrected_max_c is not None and self.corrected_max_c <= limit_c + tolerance_c
        )


Rule = Callable[[ExcursionFacts, list[str]], Optional[Verdict]]


# --- 1. Cheap non-actionable triages ------------------------------------------


def rule_insufficient_temperature(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Historical triage is not independent proof of a duplicate or an empty load."""
    values = (f.min_c, f.corrected_max_c, f.label_low_c, f.label_high_c)
    if (
        any(v is None or not isfinite(v) for v in values)
        or f.min_c > f.corrected_max_c
        or f.label_low_c > f.label_high_c
    ):
        trace.append("Escalate: insufficient temperature evidence — complete valid extrema and label range required")
        return Verdict(ESCALATE, "ACTIONABLE — insufficient temperature evidence", 0.0)
    return None


def rule_cumulative_history_unresolved(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """No verified batch identity/history exists in this pack; never assume zero."""
    if (f.stability.cumulative or f.stability.cumulative_above_label) and f.out_of_label_range is not False:
        trace.append(
            "Escalate: cumulative assessment unresolved — verified batch identity and complete prior-exposure "
            "history unavailable; remaining lifetime allowance is unknown"
        )
        return Verdict(ESCALATE, "ACTIONABLE — cumulative assessment unresolved", 0.0)
    return None


def rule_facility_equipment_event(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """INC-2502 BMS storms: facility alarms with no product loaded close automatically."""
    if "facility equipment event" not in f.triage:
        return None
    trace.append("Triage indicates facility equipment event with no product loaded")
    return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — facility equipment event, no product loaded", 0.85)


def rule_duplicate_alert(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """A duplicate of an earlier alert adds no new evidence."""
    if "duplicate" not in f.triage:
        return None
    trace.append("Triage indicates duplicate of earlier alert")
    return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — duplicate of earlier alert", 0.8)


def rule_gateway_gap(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Interpolated readings across a long gateway gap are not evidence of an excursion."""
    gap = f.gateway_gap_min
    if not (gap > 0 and f.interpolated and gap >= max(f.duration_min * GAP_SHARE_OF_EXCURSION, GAP_MIN_MINUTES)):
        return None
    trace.append(f"Gateway gap {gap} min with interpolated readings — insufficient evidence of excursion")
    disposition = RELEASE_WITH_NOTE if f.out_of_label_range else AUTO_CLOSE
    return Verdict(disposition, "NON_ACTIONABLE — sensor artefact (gap)", 0.7)


# --- 2. Hard escalations: cannot safely decide product fate --------------------


def rule_unresolved_identity(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """If we are not sure which product it is, we cannot apply its stability data."""
    if f.product.confidence >= MIN_PRODUCT_CONFIDENCE:
        return None
    trace.append("Escalate: unresolved/ambiguous product identity")
    return Verdict(ESCALATE, "ACTIONABLE — identity unresolved", 0.35)


def rule_stability_authority(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """An excursion with unestablished study applicability needs QA, not a guessed fate."""
    if f.out_of_label_range is True and f.stability.authority_issue:
        trace.append("Escalate: stability authority unresolved — " + f.stability.authority_issue)
        return Verdict(ESCALATE, "ACTIONABLE — stability authority unresolved", 0.0)
    return None


def rule_presentation_mismatch(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Never substitute unverified master prose for a mismatched study."""
    if not f.stability.presentation_mismatch_risk:
        return None
    trace.append("Escalate: stability study may be wrong presentation (vial vs pen)")
    return Verdict(ESCALATE, "ACTIONABLE — presentation mismatch risk", 0.4)


def rule_sop_overlap(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Record overlap; the final authority gate blocks release on any rule path."""
    if f.sop_overlap:
        trace.append("SOP revision overlap unresolved — no release authority established")
    return None


def rule_allowance_refer_qa(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """The study itself says 'Refer QA', so a person has to decide."""
    if not any("refer qa" in note.lower() for note in f.stability.notes or []):
        return None
    trace.append("Escalate: permitted allowance is 'Refer QA'")
    return Verdict(ESCALATE, "ACTIONABLE — allowance refer QA", 0.4)


def rule_unreadable_stability(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """A cited study we cannot read means a lab test, not a guess."""
    if f.stability.readable or not f.stability.study_ref:
        return None
    trace.append("Escalate: cited stability study unreadable")
    return Verdict(QUARANTINE_PENDING_LAB, "ACTIONABLE — unreadable stability", 0.5)


# --- 3. Benign patterns ----------------------------------------------------------


def rule_sensor_artefact(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Close a sensor artefact only when there is no gap and the peak is near the label."""
    if "sensor artefact" not in f.triage or f.gateway_gap_min != 0:
        return None
    if not f.max_within(f.label_high_c, SENSOR_ARTEFACT_TOLERANCE_C):
        return None
    trace.append("Sensor artefact triage; corrected temp near labelled range")
    return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — sensor artefact", 0.75)


def rule_dock_door(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Short dock-door ambient exposure; closes only if triage also says dock door."""
    if not (f.dock_door_open and f.duration_min <= DOCK_DOOR_MAX_MINUTES):
        return None
    if not f.max_within(f.label_high_c, DOCK_DOOR_TOLERANCE_C):
        return None
    trace.append("Short dock-door ambient exposure pattern")
    if "dock door" in f.triage:
        return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — dock door / ambient exposure", 0.7)
    return None


def rule_within_label_range(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """After the firmware correction, still inside the labelled range: nothing happened."""
    if f.out_of_label_range is not False:
        return None
    trace.append("Corrected temperatures within labelled storage range")
    return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — within labelled range", 0.9)


# --- 4. Temperature and stability arithmetic --------------------------------------


def rule_freeze_damage(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Below 0 °C on a 2–8 °C product risks freeze damage and is never released."""
    is_cold_chain = (
        f.label_high_c is not None
        and f.label_high_c <= COLD_CHAIN_MAX_LABEL_C
        and f.label_low_c is not None
        and f.label_low_c >= 0
    )
    if not (is_cold_chain and f.min_c is not None and f.min_c < 0):
        return None
    trace.append(
        f"Below 0°C on 2–8°C labelled product (min={f.min_c}) — freeze damage risk (override EXC-110483 pattern)"
    )
    return Verdict(DESTROY, "ACTIONABLE — freeze excursion", 0.75)


def rule_ultra_cold(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Ultra-cold / LN2: a very short open is likely a dry-ice top-up; a long one is a breach."""
    if f.label_low_c is None or f.label_low_c > ULTRA_COLD_LABEL_C:
        return None
    if f.duration_min <= ULTRA_COLD_TOP_UP_MINUTES:
        trace.append("Ultra-cold: ≤5 min excursion — possible dry-ice replenishment")
        return Verdict(RELEASE_WITH_NOTE, "ACTIONABLE — ultra-cold short open", 0.55)
    stab = f.stability
    if stab.no_excursion or (stab.max_duration_hours and f.duration_h > stab.max_duration_hours):
        trace.append("Ultra-cold beyond permitted hold")
        return Verdict(DESTROY, "ACTIONABLE — ultra-cold breach", 0.7)
    return None


def rule_qualified_temperature_cap(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """A cap is not permission below it; absent duration needs evidence/QA."""
    if not f.stability.qualified_cap:
        return None
    breached = f.corrected_max_c is not None and f.corrected_max_c > f.stability.max_temp_c
    trace.append(
        "Qualified temperature cap "
        + ("breached" if breached else "not breached")
        + f" (≤{f.stability.max_temp_c}°C); no duration/disposition authority supplied — QA must resolve"
    )
    return Verdict(ESCALATE, "qualified_cap_incomplete", 0.4)


def rule_no_excursion_permitted(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """The product allows no excursion: a very brief, mild breach goes to the lab, otherwise destroy."""
    if not f.stability.no_excursion:
        return None
    trace.append(f"Stability/master: no excursion permitted ({f.stability.permitted_text})")
    if f.duration_h <= BRIEF_BREACH_HOURS and f.max_within(f.label_high_c, BRIEF_BREACH_TOLERANCE_C):
        return Verdict(QUARANTINE_PENDING_LAB, "ACTIONABLE — brief breach, no-excursion product", 0.6)
    return Verdict(DESTROY, "ACTIONABLE — no excursion permitted", 0.7)


def rule_stability_allowance(f: ExcursionFacts, trace: list[str]) -> Optional[Verdict]:
    """Compare the excursion with the permitted allowance (duration and temperature)."""
    unresolved = rule_cumulative_history_unresolved(f, trace)
    if unresolved:
        return unresolved
    stab = f.stability
    has_allowance = stab.max_duration_hours is not None and (stab.max_temp_c is not None or stab.cumulative_above_label)
    if not has_allowance:
        return None

    within_duration = f.duration_h <= stab.max_duration_hours + EPSILON
    within_temp = f.corrected_max_c is not None and f.corrected_max_c <= stab.max_temp_c + 1e-6
    trace.append(
        f"Allowance check: duration {f.duration_h:.2f}h vs ≤{stab.max_duration_hours}h; "
        f"max {f.corrected_max_c}°C vs ≤{stab.max_temp_c}°C (source={stab.source})"
    )

    if within_temp and within_duration:
        trace.append("Within permitted excursion allowance")
        return Verdict(AUTO_CLOSE, "NON_ACTIONABLE — within permitted excursion allowance", 0.88)

    severe = (
        not stab.cumulative_above_label
        and f.corrected_max_c is not None
        and stab.max_temp_c is not None
        and f.corrected_max_c > stab.max_temp_c + SEVERE_BREACH_MARGIN_C
    )
    if severe:
        trace.append("Exceeded allowance temperature by >5°C")
        return Verdict(DESTROY, "ACTIONABLE — severe temperature breach", 0.7)
    trace.append("Exceeded permitted allowance — quarantine pending lab")
    return Verdict(QUARANTINE_PENDING_LAB, "ACTIONABLE — allowance exceeded", 0.65)


# --- 5. Fallback -------------------------------------------------------------------


def rule_no_parseable_allowance(f: ExcursionFacts, trace: list[str]) -> Verdict:
    """Out of range with no usable allowance: be conservative."""
    trace.append("Out of labelled range with no parseable excursion allowance")
    if f.duration_h <= MILD_EXCURSION_HOURS and f.max_within(f.label_high_c, MILD_EXCURSION_TOLERANCE_C):
        return Verdict(RELEASE_WITH_NOTE, "ACTIONABLE — brief mild excursion", 0.55)
    if f.prior_lane_excursions >= REPEAT_LANE_EXCURSIONS:
        trace.append(f"Lane has {f.prior_lane_excursions} prior excursions in 90d — cumulative trust concern")
        return Verdict(QUARANTINE_PENDING_LAB, "ACTIONABLE — repeat lane pattern", 0.55)
    return Verdict(QUARANTINE_PENDING_LAB, "ACTIONABLE — excursion confirmed", 0.5)


DECISION_RULES: tuple[Rule, ...] = (
    rule_insufficient_temperature,
    rule_cumulative_history_unresolved,
    rule_facility_equipment_event,
    rule_duplicate_alert,
    rule_gateway_gap,
    rule_unresolved_identity,
    rule_stability_authority,
    rule_presentation_mismatch,
    rule_sop_overlap,
    rule_allowance_refer_qa,
    rule_unreadable_stability,
    rule_sensor_artefact,
    rule_dock_door,
    rule_within_label_range,
    rule_freeze_damage,
    rule_ultra_cold,
    rule_qualified_temperature_cap,
    rule_no_excursion_permitted,
    rule_stability_allowance,
)


def decide(facts: ExcursionFacts) -> tuple[Verdict, list[str]]:
    """Run the rules in order and return the first verdict plus the trace of what fired."""
    trace: list[str] = []
    verdict = None
    for rule in DECISION_RULES:
        verdict = rule(facts, trace)
        if verdict is not None:
            break
    if verdict is None:
        verdict = rule_no_parseable_allowance(facts, trace)

    # Cover early gateway/ultra-cold/fallback releases as well as allowance rules.
    # In-range/noise closures are not product-release recommendations. An
    # allowance-based closure, however, depends on governing study/SOP authority.
    needs_authority = verdict.disposition in (RELEASE, RELEASE_WITH_NOTE) or (
        verdict.disposition == AUTO_CLOSE and "within permitted excursion allowance" in verdict.triage_label
    )
    if needs_authority:
        issues = []
        if facts.sop_overlap:
            issues.append("SOP revision overlap unresolved")
        if facts.sop_authority_issue:
            issues.append(facts.sop_authority_issue)
        if facts.stability.authority_issue:
            issues.append(facts.stability.authority_issue)
        if issues:
            trace.append("Escalate: release authority unresolved — " + "; ".join(issues))
            verdict = Verdict(ESCALATE, "ACTIONABLE — release authority unresolved", 0.0)
    return verdict, trace


def is_out_of_range(
    max_c: Optional[float], min_c: Optional[float], low_c: Optional[float], high_c: Optional[float]
) -> Optional[bool]:
    """True/False only for complete valid extrema and limits; otherwise unknown."""
    values = (max_c, min_c, low_c, high_c)
    if any(v is None or not isfinite(v) for v in values) or min_c > max_c or low_c > high_c:
        return None
    if high_c is not None and max_c is not None and max_c > high_c + EPSILON:
        return True
    return low_c is not None and min_c is not None and min_c < low_c - EPSILON


def _flag(value: Any) -> bool:
    return str(value or "").upper() == "Y"
