"""Enums and dataclasses shared by every layer (no framework imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Disposition(str, Enum):
    """Allowed disposition / recommendation values for an excursion case."""

    AUTO_CLOSE = "AUTO_CLOSE"
    RELEASE = "RELEASE"
    RELEASE_WITH_NOTE = "RELEASE_WITH_NOTE"
    QUARANTINE_PENDING_LAB = "QUARANTINE_PENDING_LAB"
    DESTROY = "DESTROY"
    RETURN_TO_ORIGIN = "RETURN_TO_ORIGIN"
    REWORK_RELABEL = "REWORK_RELABEL"
    ESCALATED_TO_SENIOR_QA = "ESCALATED_TO_SENIOR_QA"


ACTIONABLE = {
    Disposition.RELEASE,
    Disposition.RELEASE_WITH_NOTE,
    Disposition.QUARANTINE_PENDING_LAB,
    Disposition.DESTROY,
    Disposition.RETURN_TO_ORIGIN,
    Disposition.REWORK_RELABEL,
    Disposition.ESCALATED_TO_SENIOR_QA,
}


class CaseState(str, Enum):
    """Case lifecycle states from NEW through CLOSED_* and REOPENED."""

    NEW = "NEW"
    TRIAGED_NON_ACTIONABLE = "TRIAGED_NON_ACTIONABLE"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    RECOMMENDED = "RECOMMENDED"
    AWAITING_REVIEWER = "AWAITING_REVIEWER"
    RETURNED_FOR_DATA = "RETURNED_FOR_DATA"
    PENDING_LAB = "PENDING_LAB"
    PENDING_SECOND_SIGN = "PENDING_SECOND_SIGN"
    CLOSED_AUTO = "CLOSED_AUTO"
    CLOSED_SIGNED = "CLOSED_SIGNED"
    REOPENED = "REOPENED"


class TransitionError(ValueError):
    """Raised when a case state transition is not in the ALLOWED map."""

    pass


@dataclass
class Alert:
    """Excursion alert row shape used by API/docs; engine uses pack dicts."""

    event_id: str
    tenant_code: str
    alert_ts_utc: Optional[datetime] = None
    excursion_start_utc: Optional[datetime] = None
    excursion_end_utc: Optional[datetime] = None
    duration_min: Optional[float] = None
    min_temp_c: Optional[float] = None
    max_temp_c: Optional[float] = None
    mean_temp_c: Optional[float] = None
    product_ref_as_received: Optional[str] = None
    origin_ref_as_received: Optional[str] = None
    dest_ref_as_received: Optional[str] = None
    carrier_ref_as_received: Optional[str] = None
    lane_text: Optional[str] = None
    logger_fw: Optional[str] = None
    logger_id: Optional[str] = None
    spec_text_as_received: Optional[str] = None
    gateway_gap_min: Optional[float] = None
    interpolated: Optional[str] = None
    dock_door_open_flag: Optional[str] = None
    prior_excursions_lane_90d: Optional[int] = None
    consignment_value_usd: Optional[float] = None
    triage_outcome: Optional[str] = None
    rules_engine_recommendation: Optional[str] = None
    final_disposition: Optional[str] = None
    regulator_reportable: Optional[str] = None
    reg_window_hours: Optional[float] = None
    shipment_ref: Optional[str] = None
    source_system: Optional[str] = None
    notes: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recommendation:
    """Structured disposition recommendation emitted alongside evidence."""

    event_id: str
    tenant_code: str
    disposition: Disposition
    requires_human_signature: bool
    confidence: float
    triage_label: str
    rationale: list[str] = field(default_factory=list)
    evidence_outline: dict[str, Any] = field(default_factory=dict)
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
    reg_deadline_utc: Optional[datetime] = None
    rule_pack_version: str = "0.4.0"
    ref_snapshot_id: Optional[str] = None
    code_version: str = "0.4.0"


@dataclass
class Case:
    """Lifecycle case record (also persisted via BitemporalStore)."""

    case_id: str
    event_id: str
    tenant_code: str
    state: CaseState = CaseState.NEW
    recommendation: Optional[Disposition] = None
    final_disposition: Optional[Disposition] = None
    evidence_bundle_id: Optional[str] = None
    reg_deadline_utc: Optional[datetime] = None
    regulator_reportable: bool = False
    priority_score: float = 0.0
    reopened_from_case_id: Optional[str] = None
    reopen_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    signed_by: Optional[str] = None
    signed_at: Optional[datetime] = None


@dataclass
class EvidenceBundleMeta:
    """Hash-chain metadata for an append-only evidence bundle."""

    bundle_id: str
    content_hash: str
    prev_hash: Optional[str]
    tenant_code: str
    event_id: str
    case_id: Optional[str] = None
    created_at: Optional[datetime] = None
    retention_until: Optional[datetime] = None
    rule_pack_version: str = "0.4.0"
    ref_snapshot_id: str = ""
    code_version: str = "0.4.0"
