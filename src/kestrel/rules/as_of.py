""" "What was in force on date X?" lookups for SOPs and other dated reference data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from kestrel.utils import revision_number

"""Bitemporal-ish 'as at a date' lookups for SOPs and contracts.

We only have valid-time in the pack (effective_from / effective_to). Transaction
time is stubbed: the extract itself is the snapshot. Design doc describes the
full bitemporal model for production.
"""


@dataclass
class AsOfHit:
    """Result of an as-of SOP lookup: selected record, overlap flag, and competitors."""

    record: dict[str, Any]
    overlap_conflict: bool
    competing: list[dict[str, Any]]


def sop_in_force(
    sops: list[dict[str, Any]],
    tenant_code: str,
    title_contains: str,
    as_of: date,
) -> AsOfHit | None:
    """Select the SOP revision in force from an in-memory SOP list at as_of (highest rev on overlap)."""
    title_l = title_contains.lower()
    candidates = []
    for sop in sops:
        if sop.get("tenant_code") != tenant_code:
            continue
        if title_l not in str(sop.get("title") or "").lower():
            continue
        effective_from, effective_to = sop.get("_effective_from"), sop.get("_effective_to")
        if effective_from is None:
            continue
        if effective_from <= as_of and (effective_to is None or as_of <= effective_to):
            candidates.append(sop)
    if not candidates:
        # Also try open-ended where effective_to blank and from <= as_of
        for sop in sops:
            if sop.get("tenant_code") != tenant_code:
                continue
            if title_l not in str(sop.get("title") or "").lower():
                continue
            effective_from, effective_to = sop.get("_effective_from"), sop.get("_effective_to")
            if effective_from and effective_from <= as_of and effective_to is None:
                candidates.append(sop)
    # de-dupe by (doc_id, revision)
    uniq = {}
    for candidate in candidates:
        uniq[(candidate.get("doc_id"), candidate.get("revision"))] = candidate
    candidates = list(uniq.values())
    if not candidates:
        return None

    # Prefer highest revision number when overlap
    candidates.sort(key=lambda sop: revision_number(sop.get("revision")), reverse=True)
    return AsOfHit(
        record=candidates[0],
        overlap_conflict=len(candidates) > 1,
        competing=candidates,
    )


@dataclass(frozen=True)
class TemperatureBound:
    """One stated temperature boundary, not an inferred product restriction."""

    kind: str  # lower | upper
    value_c: float
    inclusive: bool


@dataclass(frozen=True)
class StorageLimits:
    """Explicit label bounds; additional restrictions remain separate/unverified."""

    lower: Optional[TemperatureBound] = None
    upper: Optional[TemperatureBound] = None
    constraints: tuple[str, ...] = ()
    unresolved_reason: Optional[str] = None

    @property
    def bound_type(self) -> str:
        if self.unresolved_reason or (self.lower is None and self.upper is None):
            return "unresolved"
        if self.lower and self.upper:
            return "two_sided"
        return "lower_only" if self.lower else "upper_only"

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return {**asdict(self), "bound_type": self.bound_type, "constraints": list(self.constraints)}


def parse_storage_limits(spec_text: Any) -> StorageLimits:
    """Recognise bounded storage grammar, never nominal values or implicit CRT/LN2 ranges.

    Unitless explicit ranges in this workbook's Celsius storage field retain the
    existing field-unit convention. Unknown prose/residual clauses stay unresolved.
    """
    if not spec_text or not str(spec_text).strip():
        return StorageLimits(unresolved_reason="storage instruction missing")
    text = str(spec_text).lower().replace("−", "-").replace("–", "-").replace("—", "-")
    comma_range_allowed = bool(re.match(r"^frozen\s*\(", text.strip()))
    constraints = []
    for phrase in ("do not freeze", "protect from light", "dry ice permitted"):
        if phrase in text:
            constraints.append(phrase)
            text = text.replace(phrase, "")
    excursion_note = re.search(r"excursions to [+-]?\d+(?:\.\d+)?\s*°?\s*c permitted, see stability", text)
    if excursion_note:
        constraints.append(excursion_note.group(0))
        text = text.replace(excursion_note.group(0), "")
    # Known descriptors do not supply numerical limits of their own.
    text = re.sub(r"^(?:store at|store|refrigerated|cold chain|frozen|ultra-cold|crt)\b\s*", "", text.strip())
    text = re.sub(r"\s+(?:vapour|vapor) phase ln2$", "", text.strip())
    text = text.translate(str.maketrans({"(": " ", ")": " ", ".": "."})).strip(" .;")
    text = " ".join(text.split())
    number = r"([+-]?\d+(?:\.\d+)?)"
    unit = r"\s*(?:°\s*)?c?"
    separator = r"(?:to|/|,|-)" if comma_range_allowed else r"(?:to|/|-)"
    pair = re.fullmatch(number + unit + r"\s*" + separator + r"\s*" + number + unit, text)
    if pair:
        low, high = float(pair.group(1)), float(pair.group(2))
        if low > high:
            return StorageLimits(constraints=tuple(constraints), unresolved_reason="storage bounds reversed")
        return StorageLimits(
            TemperatureBound("lower", low, True), TemperatureBound("upper", high, True), tuple(constraints)
        )
    one_sided_unit = r"\s*(?:°\s*)?c"  # No unit inference for newly recognised one-sided instructions.
    single = re.fullmatch(
        r"(below|less than|<=|≤|<|at most|not above|above|greater than|>=|≥|>|at least)\s*" + number + one_sided_unit,
        text,
    )
    if single:
        operator, value = single.group(1), float(single.group(2))
        lower = operator in {"above", "greater than", ">=", "≥", ">", "at least"}
        inclusive = operator in {"<=", "≤", "at most", "not above", ">=", "≥", "at least"}
        bound = TemperatureBound("lower" if lower else "upper", value, inclusive)
        return StorageLimits(
            lower=bound if lower else None, upper=None if lower else bound, constraints=tuple(constraints)
        )
    return StorageLimits(
        constraints=tuple(constraints),
        unresolved_reason="explicit governing temperature bounds not established from storage text",
    )


def parse_storage_range(spec_text: Any) -> tuple[Optional[float], Optional[float]]:
    """Legacy numeric view; use parse_storage_limits to preserve strictness/constraints."""
    limits = parse_storage_limits(spec_text)
    return (limits.lower.value_c if limits.lower else None, limits.upper.value_c if limits.upper else None)
