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


def parse_storage_range(spec_text: Any) -> tuple[Optional[float], Optional[float]]:
    """Best-effort parse of free-text labelled storage range -> (low, high) °C."""
    if not spec_text:
        return None, None

    text = str(spec_text)
    s_l = text.lower()
    if "ln2" in s_l or "vapour" in s_l or "vapor" in s_l or "≤ -150" in text or "<= -150" in s_l:
        return -196.0, -150.0
    if "ultra-cold" in s_l or re.search(r"-80\s*/\s*-60", text) or "-80/-60" in text.replace(" ", ""):
        match = re.search(r"(-?\d+)\s*/\s*(-?\d+)", text)
        if match:
            first, second = float(match.group(1)), float(match.group(2))
            return min(first, second), max(first, second)
        return -80.0, -60.0
    if re.search(r"-25\s*/?\s*-15|-25/-15", text.replace(" ", "")):
        return -25.0, -15.0
    # Prefer explicit range patterns before bare number extraction so "2-8" is
    # not parsed as (-8, 2) via a leading-minus token.
    match = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*[–\-~/to]+\s*(\d+(?:\.\d+)?)\s*°?\s*c?",
        s_l,
    )
    if match:
        first, second = float(match.group(1)), float(match.group(2))
        return min(first, second), max(first, second)
    match = re.search(r"\+?(\d+)\s*/\s*\+?(\d+)", text)
    if match:
        first, second = float(match.group(1)), float(match.group(2))
        return min(first, second), max(first, second)
    if "crt" in s_l:
        return 15.0, 25.0
    if "below 25" in s_l:
        return None, 25.0
    return None, None
