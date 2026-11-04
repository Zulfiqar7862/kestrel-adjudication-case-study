"""Bitemporal-ish 'as at a date' lookups for SOPs and contracts.

We only have valid-time in the pack (effective_from / effective_to). Transaction
time is stubbed: the extract itself is the snapshot. Design doc describes the
full bitemporal model for production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


@dataclass
class AsOfHit:
    record: dict[str, Any]
    overlap_conflict: bool
    competing: list[dict[str, Any]]


def sop_in_force(
    sops: list[dict[str, Any]],
    tenant_code: str,
    title_contains: str,
    as_of: date,
) -> AsOfHit | None:
    title_l = title_contains.lower()
    candidates = []
    for s in sops:
        if s.get("tenant_code") != tenant_code:
            continue
        if title_l not in str(s.get("title") or "").lower():
            continue
        ef, et = s.get("_effective_from"), s.get("_effective_to")
        if ef is None:
            continue
        if ef <= as_of and (et is None or as_of <= et):
            candidates.append(s)
    if not candidates:
        # Also try open-ended where effective_to blank and from <= as_of
        for s in sops:
            if s.get("tenant_code") != tenant_code:
                continue
            if title_l not in str(s.get("title") or "").lower():
                continue
            ef, et = s.get("_effective_from"), s.get("_effective_to")
            if ef and ef <= as_of and et is None:
                candidates.append(s)
    # de-dupe by (doc_id, revision)
    uniq = {}
    for c in candidates:
        uniq[(c.get("doc_id"), c.get("revision"))] = c
    candidates = list(uniq.values())
    if not candidates:
        return None
    # Prefer highest revision number when overlap
    def rev_key(r: dict[str, Any]) -> int:
        rev = str(r.get("revision") or "")
        digits = "".join(ch for ch in rev if ch.isdigit())
        return int(digits) if digits else 0

    candidates.sort(key=rev_key, reverse=True)
    return AsOfHit(
        record=candidates[0],
        overlap_conflict=len(candidates) > 1,
        competing=candidates,
    )


def parse_storage_range(spec_text: Any) -> tuple[Optional[float], Optional[float]]:
    """Best-effort parse of free-text labelled storage range -> (low, high) °C."""
    if not spec_text:
        return None, None
    import re

    s = str(spec_text)
    s_l = s.lower()
    if "ln2" in s_l or "vapour" in s_l or "vapor" in s_l or "≤ -150" in s or "<= -150" in s_l:
        return -196.0, -150.0
    if "ultra-cold" in s_l or re.search(r"-80\s*/\s*-60", s) or "-80/-60" in s.replace(" ", ""):
        m = re.search(r"(-?\d+)\s*/\s*(-?\d+)", s)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            return min(a, b), max(a, b)
        return -80.0, -60.0
    if re.search(r"-25\s*/?\s*-15|-25/-15", s.replace(" ", "")):
        return -25.0, -15.0
    # Prefer explicit range patterns before bare number extraction so "2-8" is
    # not parsed as (-8, 2) via a leading-minus token.
    m = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*[–\-~/to]+\s*(\d+(?:\.\d+)?)\s*°?\s*c?",
        s_l,
    )
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b)
    m = re.search(r"\+?(\d+)\s*/\s*\+?(\d+)", s)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b)
    if "crt" in s_l:
        return 15.0, 25.0
    if "below 25" in s_l:
        return None, 25.0
    return None, None
