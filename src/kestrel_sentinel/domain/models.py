from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .enums import CaseState, Disposition


class Alert(BaseModel):
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
    raw: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    event_id: str
    tenant_code: str
    disposition: Disposition
    requires_human_signature: bool
    confidence: float
    triage_label: str
    rationale: list[str] = Field(default_factory=list)
    evidence_outline: dict[str, Any] = Field(default_factory=dict)
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
    rule_pack_version: str = "0.2.0"
    ref_snapshot_id: Optional[str] = None
    code_version: str = "0.2.0"


class Case(BaseModel):
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
    created_at: datetime
    updated_at: datetime
    signed_by: Optional[str] = None
    signed_at: Optional[datetime] = None


class EvidenceBundleMeta(BaseModel):
    bundle_id: str
    content_hash: str
    prev_hash: Optional[str]
    tenant_code: str
    event_id: str
    case_id: Optional[str] = None
    created_at: datetime
    retention_until: datetime
    rule_pack_version: str
    ref_snapshot_id: str
    code_version: str
