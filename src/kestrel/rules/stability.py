"""Stability-study and storage-range parsing; permitted-excursion evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from kestrel.ingest import DataPack
from kestrel.rules.identity import ResolvedProduct, _norm, _presentation_from_text

"""Resolve stability / permitted excursion allowance for a product as cited."""


@dataclass
class StabilityPosition:
    """Parsed stability allowance for a resolved product (readable text, caps, flags)."""

    study_ref: Optional[str]
    permitted_text: Optional[str]
    readable: bool
    source: str  # stability_index | unresolved (legacy values may exist in test fixtures)
    max_temp_c: Optional[float] = None
    max_duration_hours: Optional[float] = None
    cumulative: bool = False
    once_only: bool = False
    qualified_cap: bool = False
    no_excursion: bool = False
    freeze_sensitive: bool = False
    presentation_mismatch_risk: bool = False
    cumulative_above_label: bool = False  # "72h above 8°C" — 8 is threshold, not cap
    authority_issue: Optional[str] = None
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
    """Resolves uniquely cited excursion-study applicability without master fallback."""

    def __init__(self, pack: DataPack) -> None:
        """Bind the resolver to a loaded DataPack."""
        self.pack = pack
        self.by_ref: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for study in pack.stability:
            self.by_ref.setdefault((study.get("tenant_code"), str(study.get("study_ref"))), []).append(study)

    def discover(
        self,
        product: ResolvedProduct,
        *,
        knowledge_date=None,
        event_date=None,
        min_temp_c=None,
        max_temp_c=None,
        duration_min=None,
        sop_authority="UNKNOWN",
        prior_exposure_hours=None,
    ):
        """Catalogue every tenant-owned candidate; never infer missing authority."""
        from kestrel.rules.study_discovery import discover_studies

        return discover_studies(
            self.pack.stability,
            product,
            knowledge_date=knowledge_date,
            event_date=event_date,
            min_temp_c=min_temp_c,
            max_temp_c=max_temp_c,
            duration_min=duration_min,
            sop_authority=sop_authority,
            prior_exposure_hours=prior_exposure_hours,
        )

    def resolve(self, product: ResolvedProduct) -> StabilityPosition:
        """Use only a uniquely cited, product/presentation-aligned excursion study.

        The index supplies no effective dates or verified alternate-study mapping.
        Do not substitute an uncited study or product-master prose for authority.
        """
        notes: list[str] = []
        study_ref = product.stability_study_ref
        master_text = product.permitted_excursion_text
        matches = self.by_ref.get((product.tenant_code, str(study_ref)), []) if study_ref else []
        study = matches[0] if len(matches) == 1 else None
        issues = []
        if study is None:
            issues.append("cited study missing or ambiguous in tenant index")
        else:
            text = _norm(study.get("product_text_as_written"))
            brand = _norm(product.brand)
            if not brand or not re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", text):
                issues.append("study product identity not established")
            hint = product.presentation_hint
            if not hint or _presentation_from_text(text) != hint:
                issues.append("study presentation applicability not established")
            # A row can contain a labelled brand and a contradictory suffix.
            if (hint == "pen" and "vial" in text) or (hint == "pfs" and "vial" in text):
                issues.append("study presentation conflicts with product")
            if "excursion" not in _norm(study.get("study_type")):
                issues.append("study type does not establish excursion allowance")
        if issues:
            reason = "; ".join(issues)
            return StabilityPosition(
                study_ref=study_ref,
                permitted_text=None,
                readable=False,
                source="unresolved",
                authority_issue=reason,
                presentation_mismatch_risk=any("presentation" in issue for issue in issues),
                notes=["Stability authority unresolved: " + reason + "; product-master text not used as substitute"],
            )

        # "Partial" readability does not establish a usable full allowance.
        readable = str(study.get("readable") or "").upper() == "Y"
        study_text = study.get("permitted_excursion_text") or ""
        if not study_text or not readable or str(study.get("readable") or "").upper() != "Y":
            return StabilityPosition(
                study_ref=study_ref,
                permitted_text=None,
                readable=readable,
                source="unresolved",
                authority_issue="applicable study allowance missing or not fully readable",
                notes=notes + ["Stability authority unresolved; product-master text not used as substitute"],
            )
        parsed = _parse_allowance(str(study_text))
        source = "stability_index"
        text = study_text
        if master_text and str(master_text).strip() != str(study_text).strip():
            notes.append(f"Master allowance differs from study; not used: {master_text!r}")
        if parsed.get("refer_qa"):
            notes.append("Study says Refer QA")

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
            cumulative_above_label=bool(parsed.get("cumulative_above_label")),
            notes=notes,
        )
