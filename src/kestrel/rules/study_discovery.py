"""Tenant-scoped study search with explicit admissibility failures.

Optional authority metadata is never synthesized from filenames or index presence.
The workbook lacks it; UNKNOWN is an expected result, not a repair to its data.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from kestrel.rules.as_of import parse_storage_limits
from kestrel.rules.identity import ResolvedProduct, _norm, _presentation_from_text
from kestrel.utils import parse_date


class StudyRejectionCode(str, Enum):
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    WRONG_TENANT = "WRONG_TENANT"
    CITED_STUDY_OUTSIDE_TENANT_SCOPE = "CITED_STUDY_OUTSIDE_TENANT_SCOPE"
    CITATION_MISSING = "CITATION_MISSING"
    AMBIGUOUS_CITATION = "AMBIGUOUS_CITATION"
    UNCITED_MAPPING_UNKNOWN = "UNCITED_MAPPING_UNKNOWN"
    WRONG_PRODUCT = "WRONG_PRODUCT"
    STRENGTH_MISMATCH = "STRENGTH_MISMATCH"
    STRENGTH_UNKNOWN = "STRENGTH_UNKNOWN"
    PRESENTATION_MISMATCH = "PRESENTATION_MISMATCH"
    PRESENTATION_UNKNOWN = "PRESENTATION_UNKNOWN"
    NOT_EXCURSION_STUDY = "NOT_EXCURSION_STUDY"
    UNREADABLE = "UNREADABLE"
    APPROVAL_UNKNOWN = "APPROVAL_UNKNOWN"
    NOT_APPROVED = "NOT_APPROVED"
    EFFECTIVITY_UNKNOWN = "EFFECTIVITY_UNKNOWN"
    NOT_EFFECTIVE = "NOT_EFFECTIVE"
    KNOWLEDGE_TIME_UNKNOWN = "KNOWLEDGE_TIME_UNKNOWN"
    NOT_KNOWN_AT_TIME = "NOT_KNOWN_AT_TIME"
    SUPERSEDED = "SUPERSEDED"
    SUPERSESSION_UNKNOWN = "SUPERSESSION_UNKNOWN"
    ALLOWANCE_MISSING = "ALLOWANCE_MISSING"
    ALLOWANCE_UNPARSEABLE = "ALLOWANCE_UNPARSEABLE"
    REQUIRES_QA = "REQUIRES_QA"
    TEMPERATURE_MISSING = "TEMPERATURE_MISSING"
    TEMPERATURE_NOT_COVERED = "TEMPERATURE_NOT_COVERED"
    TEMPERATURE_RANGE_UNKNOWN = "TEMPERATURE_RANGE_UNKNOWN"
    DURATION_MISSING = "DURATION_MISSING"
    DURATION_NOT_COVERED = "DURATION_NOT_COVERED"
    CUMULATIVE_HISTORY_UNKNOWN = "CUMULATIVE_HISTORY_UNKNOWN"
    CUMULATIVE_EXCEEDED = "CUMULATIVE_EXCEEDED"
    ONCE_ONLY_HISTORY_UNKNOWN = "ONCE_ONLY_HISTORY_UNKNOWN"
    CONFLICTING_SOP = "CONFLICTING_SOP"
    SOP_AUTHORITY_UNKNOWN = "SOP_AUTHORITY_UNKNOWN"


@dataclass
class StudyRejection:
    code: StudyRejectionCode
    detail: str
    assessment: str = "REJECTED"  # UNKNOWN means not established, not disproven


@dataclass
class StudyCandidate:
    study_ref: Optional[str]
    source_sheet: Optional[str]
    source_row: Optional[int]
    product_text: Optional[str]
    study_type: Optional[str]
    permitted_text: Optional[str]
    cited: bool
    status: str
    rejections: list[StudyRejection] = field(default_factory=list)


@dataclass
class StudyDiscovery:
    tenant_code: str
    cited_study_ref: Optional[str]
    selected_study_ref: Optional[str]
    status: str
    event_date: Optional[str]
    knowledge_date: Optional[str]
    candidates: list[StudyCandidate] = field(default_factory=list)
    reasons: list[StudyRejection] = field(default_factory=list)
    scope: str = "All tenant-owned index rows, in source order; foreign/unowned rows excluded before search"
    authority_limit: str = "Index assertions only, not authenticated full-report or clinical release authority"

    def assessment(self) -> dict[str, Any]:
        return asdict(self)


def _date(value: Any) -> Optional[date]:
    """Malformed optional authority metadata is missing evidence, not an engine crash."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        return None


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _strengths(text: str) -> set[tuple[float, str]]:
    return {
        (float(n), u.replace(" ", ""))
        for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*((?:mcg|mg|ng|g|iu|u)(?:\s*/\s*(?:ml|l))?)(?![a-z])", _norm(text))
    }


def _name(text: str) -> str:
    """Conservative brand comparison, without inferring synonyms or conversions."""
    text = re.sub(r"\d+(?:\.\d+)?\s*(?:mcg|mg|ng|g|iu|u)(?:\s*/\s*(?:ml|l))?\b", " ", _norm(text))
    text = re.sub(r"\b(?:pre-filled syringe|pre-filled|syringe|pfs|pen|vial)\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def evaluate_candidate(
    row: dict[str, Any],
    product: ResolvedProduct,
    *,
    cited_count: int,
    knowledge_date: Optional[date],
    event_date: Optional[date],
    min_temp_c: Optional[float],
    max_temp_c: Optional[float],
    duration_min: Optional[float],
    sop_authority: str,
    prior_exposure_hours: Optional[float],
) -> StudyCandidate:
    from kestrel.rules.stability import _parse_allowance

    reasons: list[StudyRejection] = []

    def reject(code: str, detail: str, unknown: bool = False) -> None:
        reasons.append(StudyRejection(StudyRejectionCode(code), detail, "UNKNOWN" if unknown else "REJECTED"))

    cited = bool(product.stability_study_ref and row.get("study_ref") == product.stability_study_ref)
    if row.get("tenant_code") != product.tenant_code:
        # Defensive public helper: do not return any foreign source material.
        return StudyCandidate(
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            "REJECTED",
            [StudyRejection(StudyRejectionCode.WRONG_TENANT, "Candidate not owned by event tenant")],
        )
    if not product.release_identity_eligible:
        reject("IDENTITY_UNRESOLVED", "Typed tenant product identity is not established", True)
    if not cited:
        reject(
            "UNCITED_MAPPING_UNKNOWN",
            "No verified alternate-study mapping; discovery does not promote an uncited row",
            True,
        )
    elif cited_count != 1:
        reject("AMBIGUOUS_CITATION", "Multiple tenant rows carry the cited reference")
    text = str(row.get("product_text_as_written") or "")
    brand = str(product.brand or "")
    if not _name(brand) or (
        _name(brand) != _name(text) and not re.search(r"(?<!\w)" + re.escape(_norm(brand)) + r"(?!\w)", _norm(text))
    ):
        reject("WRONG_PRODUCT", "Study product text does not establish the labelled product; synonyms not inferred")
    ps, ss = _strengths(brand), _strengths(text)
    if not ps or not ss:
        reject("STRENGTH_UNKNOWN", "Explicit comparable product/study strength and unit missing", True)
    elif ps != ss:
        reject("STRENGTH_MISMATCH", "Product and study strength/unit signatures differ; no unit conversion inferred")
    hint = product.presentation_hint
    form = _presentation_from_text(text)
    # A precedence-based form parser must not conceal contradictory descriptors.
    normalized_text = _norm(text)
    explicit_forms = {
        kind
        for kind, pattern in (
            ("pen", r"\b(?:pen|solojet)\b"),
            ("pfs", r"\b(?:pfs|syringe|pre-filled)\b"),
            ("vial", r"\bvial\b"),
            ("oral", r"\b(?:tabs|tablet|sachet)\b"),
        )
        if re.search(pattern, normalized_text)
    }
    if not hint or not form:
        reject("PRESENTATION_UNKNOWN", "Explicit comparable presentation missing", True)
    elif hint != form or len(explicit_forms) > 1:
        reject("PRESENTATION_MISMATCH", "Study presentation conflicts with product, including contradictory suffixes")
    if "excursion" not in _norm(row.get("study_type")):
        reject("NOT_EXCURSION_STUDY", "Study type does not establish an excursion allowance")
    if _norm(row.get("readable")) != "y":
        reject("UNREADABLE", "Index does not assert fully readable evidence", True)
    approval = _norm(row.get("approval_status"))
    if not approval:
        reject("APPROVAL_UNKNOWN", "Approval metadata absent from supplied index", True)
    elif approval != "approved":
        reject("NOT_APPROVED", "Study is not explicitly approved")
    start, end = _date(row.get("effective_from")), _date(row.get("effective_to"))
    if not start or not end or not event_date:
        reject(
            "EFFECTIVITY_UNKNOWN",
            "Effective interval or event date absent/unparseable; no open interval inferred",
            True,
        )
    elif start > end or not start <= event_date <= end or (knowledge_date and start > knowledge_date):
        reject("NOT_EFFECTIVE", "Study effective interval does not cover event/knowledge time")
    known = _date(row.get("known_from"))
    if not known or not knowledge_date:
        reject("KNOWLEDGE_TIME_UNKNOWN", "Study availability at requested knowledge time not established", True)
    elif known > knowledge_date:
        reject("NOT_KNOWN_AT_TIME", "Study availability is later than requested knowledge time")
    superseded = _norm(row.get("superseded"))
    if superseded == "y":
        reject("SUPERSEDED", "Explicit supersession assertion; filenames are never interpreted as status")
    elif superseded != "n":
        reject("SUPERSESSION_UNKNOWN", "Supersession status not supplied", True)
    allowance = str(row.get("permitted_excursion_text") or "")
    parsed = _parse_allowance(allowance)
    if not allowance:
        reject("ALLOWANCE_MISSING", "Permitted-excursion text absent", True)
    elif parsed.get("refer_qa"):
        reject("REQUIRES_QA", "Study directs review, not automatic selection")
    elif not parsed.get("max_duration_hours") or parsed.get("max_temp_c") is None:
        reject(
            "ALLOWANCE_UNPARSEABLE",
            "No complete numeric allowance: no duration/disposition authority established; prohibition alone is not permission",
            True,
        )
    if not _finite(min_temp_c) or not _finite(max_temp_c) or min_temp_c > max_temp_c:
        reject("TEMPERATURE_MISSING", "Valid two-sided event temperature summary unavailable", True)
    else:
        limits = parse_storage_limits(product.storage_spec_text)
        if (
            parsed.get("cumulative_above_label")
            or parsed.get("max_temp_c") is None
            or not limits.lower
            or min_temp_c < limits.lower.value_c
        ):
            reject(
                "TEMPERATURE_RANGE_UNKNOWN",
                "No established full envelope for this event; an above-label threshold is not a tested maximum",
                True,
            )
        else:
            cap = parsed["max_temp_c"]
            strict = bool(
                re.search(
                    r"\bbelow\s+" + re.escape(str(int(cap) if float(cap).is_integer() else cap)) + r"\b",
                    _norm(allowance),
                )
            )
            if max_temp_c > cap or (strict and max_temp_c == cap):
                reject(
                    "TEMPERATURE_NOT_COVERED", "Event upper-bound scenario exceeds allowance (strict below preserved)"
                )
    if not _finite(duration_min) or duration_min < 0:
        reject("DURATION_MISSING", "Valid event duration absent", True)
    elif parsed.get("max_duration_hours") is not None and duration_min / 60 > parsed["max_duration_hours"]:
        reject("DURATION_NOT_COVERED", "Current exposure exceeds stated allowance")
    once_only = parsed.get("once_only") or bool(re.search(r"\b(?:one|single) excursion\b", _norm(allowance)))
    if parsed.get("cumulative") or once_only:
        if not _finite(prior_exposure_hours) or prior_exposure_hours < 0:
            reject(
                "CUMULATIVE_HISTORY_UNKNOWN" if parsed.get("cumulative") else "ONCE_ONLY_HISTORY_UNKNOWN",
                "Verified batch identity and complete applicable prior exposure not supplied",
                True,
            )
        elif once_only and prior_exposure_hours > 0:
            reject("CUMULATIVE_EXCEEDED", "Prior exposure precludes once-only allowance")
        elif (
            parsed.get("max_duration_hours") is not None
            and duration_min is not None
            and prior_exposure_hours + duration_min / 60 > parsed["max_duration_hours"]
        ):
            reject("CUMULATIVE_EXCEEDED", "Prior plus current exposure exceeds stated cumulative allowance")
    if sop_authority == "CONFLICT":
        reject("CONFLICTING_SOP", "Governing SOP revisions conflict")
    elif sop_authority != "ESTABLISHED":
        reject(
            "SOP_AUTHORITY_UNKNOWN",
            "Governing site/SOP acceptance limits unavailable; index pointers are not authority",
            True,
        )
    return StudyCandidate(
        row.get("study_ref"),
        row.get("_source_sheet"),
        row.get("_source_row"),
        text,
        row.get("study_type"),
        allowance or None,
        cited,
        "REJECTED" if reasons else "SELECTED",
        reasons,
    )


def discover_studies(rows: list[dict[str, Any]], product: ResolvedProduct, **context: Any) -> StudyDiscovery:
    own = [row for row in rows if row.get("tenant_code") == product.tenant_code]
    count = sum(row.get("study_ref") == product.stability_study_ref for row in own)
    candidates = [evaluate_candidate(row, product, cited_count=count, **context) for row in own]
    reasons = []
    if not product.stability_study_ref:
        reasons.append(
            StudyRejection(StudyRejectionCode.CITATION_MISSING, "No product study citation supplied", "UNKNOWN")
        )
    elif not count:
        reasons.append(
            StudyRejection(
                StudyRejectionCode.CITED_STUDY_OUTSIDE_TENANT_SCOPE,
                "Cited study not in tenant scope (absent or foreign); foreign rows not searched",
                "UNKNOWN",
            )
        )
    selected = [c.study_ref for c in candidates if c.status == "SELECTED"]
    return StudyDiscovery(
        product.tenant_code,
        product.stability_study_ref,
        selected[0] if len(selected) == 1 else None,
        "SELECTED" if len(selected) == 1 else "UNRESOLVED",
        str(context["event_date"]) if context["event_date"] else None,
        str(context["knowledge_date"]) if context["knowledge_date"] else None,
        candidates,
        reasons,
    )
