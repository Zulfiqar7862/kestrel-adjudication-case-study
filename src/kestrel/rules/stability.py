"""Stability-study and storage-range parsing; permitted-excursion evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from kestrel.ingest import DataPack
from kestrel.rules.identity import ResolvedProduct

"""Resolve stability / permitted excursion allowance for a product as cited."""


@dataclass
class StabilityPosition:
    """Parsed stability allowance for a resolved product (readable text, caps, flags)."""

    study_ref: Optional[str]
    permitted_text: Optional[str]
    readable: bool
    source: str  # product_master | stability_index | both | none
    max_temp_c: Optional[float] = None
    max_duration_hours: Optional[float] = None
    cumulative: bool = False
    once_only: bool = False
    qualified_cap: bool = False
    no_excursion: bool = False
    freeze_sensitive: bool = False
    presentation_mismatch_risk: bool = False
    cumulative_above_label: bool = False  # "72h above 8°C" — 8 is threshold, not cap
    notes: list[str] = None

    def __post_init__(self) -> None:
        """Derive structured fields from permitted_excursion_text after init."""
        if self.notes is None:
            self.notes = []


def _parse_allowance(text: str) -> dict[str, Any]:
    """Parse free-text permitted-excursion language into structured allowance fields."""
    text_clean = (text or "").strip()
    out: dict[str, Any] = {
        "no_excursion": False,
        "cumulative": False,
        "once_only": False,
        "max_temp_c": None,
        "max_duration_hours": None,
        "refer_qa": False,
        "freeze_sensitive": "do not freeze" in text_clean.lower(),
        "cumulative_above_label": False,
    }
    text_lower = text_clean.lower()
    if not text_clean:
        return out
    if "refer qa" in text_lower:
        out["refer_qa"] = True
        return out
    cap = re.search(r"no excursions? above\s*(-?\d+(?:\.\d+)?)\s*°?\s*c", text_lower)
    if cap:
        out["qualified_cap"] = True
        out["max_temp_c"] = float(cap.group(1))
        return out
    if "no excursion" in text_lower:
        out["no_excursion"] = True
        return out
    if "cumulative" in text_lower:
        out["cumulative"] = True
    if "once" in text_lower:
        out["once_only"] = True
    # ≤ 6 h to 15 °C
    m = re.search(
        r"(?:≤|<=)?\s*(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*(?:to|below|at|above)?\s*(\d+(?:\.\d+)?)\s*°?\s*c",
        text_lower,
    )
    if m:
        out["max_duration_hours"] = float(m.group(1))
        out["max_temp_c"] = float(m.group(2))
    m2 = re.search(
        r"cumulative\s+(\d+)\s*h(?:ours?)?\s*above\s*(\d+(?:\.\d+)?)",
        text_lower,
    )
    if m2:
        out["max_duration_hours"] = float(m2.group(1))
        out["max_temp_c"] = float(m2.group(2))  # labelled threshold, not absolute cap
        out["cumulative"] = True
        out["cumulative_above_label"] = True
    m3 = re.search(
        r"excursions?\s+to\s+(\d+(?:\.\d+)?)\s*c?\s*up\s+to\s+(\d+)\s*days?",
        text_lower,
    )
    if m3:
        out["max_temp_c"] = float(m3.group(1))
        out["max_duration_hours"] = float(m3.group(2)) * 24
        out["cumulative"] = True
    m4 = re.search(
        r"single excursion\s*≤\s*(\d+)\s*h\s*to\s*(\d+)",
        text_lower,
    )
    if m4:
        out["max_duration_hours"] = float(m4.group(1))
        out["max_temp_c"] = float(m4.group(2))
        out["once_only"] = True
    return out


class StabilityResolver:
    """Resolves stability study / master permitted-excursion text for a product."""

    def __init__(self, pack: DataPack) -> None:
        """Bind the resolver to a loaded DataPack."""
        self.pack = pack
        self.by_ref = {
            (study.get("tenant_code"), str(study.get("study_ref"))): study
            for study in pack.stability
            if study.get("study_ref")
        }

    def resolve(self, product: ResolvedProduct) -> StabilityPosition:
        """Return the stability position for a resolved product (master preferred on mismatch)."""
        notes: list[str] = []
        study_ref = product.stability_study_ref
        master_text = product.permitted_excursion_text
        study = self.by_ref.get((product.tenant_code, str(study_ref))) if study_ref else None

        if study_ref and not study:
            notes.append(
                f"product master cites {study_ref} but it is absent from 06_Stability_Index "
                "(index covers ~60% of repository — pack README)"
            )

        presentation_risk = False
        if study and product.brand:
            study_prod = str(study.get("product_text_as_written") or "").lower()
            # vial vs pen mismatch — the EXC-110497 failure mode
            brand_l = product.brand.lower()
            if ("vial" in study_prod and "pen" in brand_l) or ("pen" in study_prod and "vial" in brand_l):
                presentation_risk = True
                notes.append(
                    f"presentation mismatch risk: master brand {product.brand!r} vs study "
                    f"{study.get('product_text_as_written')!r}"
                )
            if product.presentation_hint == "pen" and "vial" in study_prod:
                presentation_risk = True
            if product.presentation_hint == "vial" and "pen" in study_prod:
                presentation_risk = True

        study_text = None
        readable = True
        if study:
            readable = str(study.get("readable") or "Y").upper().startswith("Y") or str(
                study.get("readable")
            ).startswith("Partial")
            if str(study.get("readable") or "").startswith("N"):
                readable = False
                notes.append("stability study marked unreadable (scan of scan)")
            study_text = study.get("permitted_excursion_text") or ""
            if not study_text:
                notes.append(
                    "stability study has blank permitted_excursion_text "
                    "(long-term/accelerated studies do not answer excursion question — README)"
                )

        # Prefer study excursion text when present, readable, and presentation-aligned.
        # Pack trap (EXC-107133 / T-KAVERI): master brand is SoloJet (pen) but cited
        # STB-3584 is indexed as vial — use master permitted text instead of the
        # mismatched study (EXC-110497 failure mode).
        if presentation_risk and master_text and str(master_text).strip():
            notes.append(
                "cited study presentation conflicts with brand; preferring product-master "
                "permitted_excursion_text over mismatched study row"
            )
            parsed = _parse_allowance(str(master_text))
            source = "product_master_over_mismatched_study"
            text = master_text
            if parsed.get("refer_qa"):
                notes.append("master says 'Refer QA' — not a usable allowance (override EXC-110574)")
        elif study_text and readable:
            parsed = _parse_allowance(str(study_text))
            source = "stability_index"
            text = study_text
            if master_text and str(master_text).strip() and str(master_text).strip() != str(study_text).strip():
                notes.append(f"master permitted_excursion_text differs from study: master={master_text!r}")
                source = "both"
        elif master_text:
            parsed = _parse_allowance(str(master_text))
            source = "product_master"
            text = master_text
            if parsed.get("refer_qa"):
                notes.append("master says 'Refer QA' — not a usable allowance (override EXC-110574)")
        else:
            return StabilityPosition(
                study_ref=study_ref,
                permitted_text=None,
                readable=readable,
                source="none",
                presentation_mismatch_risk=presentation_risk,
                notes=notes + ["no permitted excursion text available"],
            )

        return StabilityPosition(
            study_ref=str(study_ref) if study_ref else None,
            permitted_text=str(text) if text else None,
            readable=readable,
            source=source,
            max_temp_c=parsed.get("max_temp_c"),
            max_duration_hours=parsed.get("max_duration_hours"),
            cumulative=bool(parsed.get("cumulative")),
            once_only=bool(parsed.get("once_only")),
            no_excursion=bool(parsed.get("no_excursion")),
            qualified_cap=bool(parsed.get("qualified_cap")),
            freeze_sensitive=bool(parsed.get("freeze_sensitive")),
            presentation_mismatch_risk=presentation_risk,
            cumulative_above_label=bool(parsed.get("cumulative_above_label")),
            notes=notes,
        )
