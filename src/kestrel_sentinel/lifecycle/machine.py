from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from kestrel_sentinel.domain.enums import CaseState, Disposition, TransitionError, ACTIONABLE
from kestrel_sentinel.store.bitemporal import BitemporalStore


ALLOWED: dict[CaseState, set[CaseState]] = {
    CaseState.NEW: {
        CaseState.TRIAGED_NON_ACTIONABLE,
        CaseState.PENDING_EVIDENCE,
        CaseState.RECOMMENDED,
        CaseState.AWAITING_REVIEWER,
    },
    CaseState.TRIAGED_NON_ACTIONABLE: {CaseState.CLOSED_AUTO, CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_EVIDENCE: {CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER},
    CaseState.RECOMMENDED: {
        CaseState.AWAITING_REVIEWER,
        CaseState.RETURNED_FOR_DATA,
        CaseState.PENDING_LAB,
        CaseState.PENDING_SECOND_SIGN,
        CaseState.CLOSED_SIGNED,
        CaseState.CLOSED_AUTO,
    },
    CaseState.AWAITING_REVIEWER: {
        CaseState.RETURNED_FOR_DATA,
        CaseState.PENDING_LAB,
        CaseState.PENDING_SECOND_SIGN,
        CaseState.CLOSED_SIGNED,
    },
    CaseState.RETURNED_FOR_DATA: {CaseState.PENDING_EVIDENCE, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_LAB: {CaseState.CLOSED_SIGNED, CaseState.AWAITING_REVIEWER},
    CaseState.PENDING_SECOND_SIGN: {CaseState.CLOSED_SIGNED},
    CaseState.CLOSED_AUTO: {CaseState.REOPENED},
    CaseState.CLOSED_SIGNED: {CaseState.REOPENED},
    CaseState.REOPENED: {CaseState.RECOMMENDED, CaseState.AWAITING_REVIEWER, CaseState.PENDING_EVIDENCE},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CaseLifecycle:
    def __init__(self, store: BitemporalStore):
        self.store = store

    def create(
        self,
        *,
        event_id: str,
        tenant_code: str,
        reg_deadline_utc: Optional[datetime],
        regulator_reportable: bool,
        recommendation: Optional[Disposition] = None,
        evidence_bundle_id: Optional[str] = None,
        reopened_from: Optional[str] = None,
        reopen_reason: Optional[str] = None,
    ) -> dict:
        now = _utcnow()
        # Priority: reportable with nearer deadline sorts first via store queue
        priority = 100.0 if regulator_reportable else 10.0
        if recommendation == Disposition.AUTO_CLOSE:
            state = CaseState.TRIAGED_NON_ACTIONABLE
        elif recommendation in ACTIONABLE:
            state = CaseState.AWAITING_REVIEWER
        else:
            state = CaseState.NEW
        if reopened_from:
            state = CaseState.REOPENED
        case = {
            "case_id": f"CASE-{uuid4().hex[:12]}",
            "event_id": event_id,
            "tenant_code": tenant_code,
            "state": state.value,
            "recommendation": recommendation.value if recommendation else None,
            "final_disposition": None,
            "evidence_bundle_id": evidence_bundle_id,
            "reg_deadline_utc": reg_deadline_utc.isoformat(sep=" ") if reg_deadline_utc else None,
            "regulator_reportable": regulator_reportable,
            "priority_score": priority,
            "reopened_from_case_id": reopened_from,
            "reopen_reason": reopen_reason,
            "created_at": now.isoformat(sep=" "),
            "updated_at": now.isoformat(sep=" "),
            "signed_by": None,
            "signed_at": None,
        }
        self.store.save_case(case)
        return case

    def transition(self, case_id: str, new_state: CaseState, **patch) -> dict:
        case = self.store.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        cur = CaseState(case["state"])
        if new_state not in ALLOWED.get(cur, set()):
            raise TransitionError(f"{cur.value} -> {new_state.value} not allowed")
        case["state"] = new_state.value
        case["updated_at"] = _utcnow().isoformat(sep=" ")
        case.update({k: v for k, v in patch.items() if v is not None})
        self.store.save_case(case)
        return case

    def sign(self, case_id: str, signed_by: str, disposition: Disposition) -> dict:
        case = self.transition(
            case_id,
            CaseState.CLOSED_SIGNED,
            final_disposition=disposition.value,
            signed_by=signed_by,
            signed_at=_utcnow().isoformat(sep=" "),
        )
        return case

    def reopen(self, case_id: str, reason: str) -> dict:
        """Reopen months later — new case revision linked to prior."""
        prior = self.store.get_case(case_id)
        if not prior:
            raise KeyError(case_id)
        self.transition(case_id, CaseState.REOPENED, reopen_reason=reason)
        return self.create(
            event_id=prior["event_id"],
            tenant_code=prior["tenant_code"],
            reg_deadline_utc=None,  # notification already handled historically
            regulator_reportable=False,
            recommendation=Disposition(prior["recommendation"]) if prior.get("recommendation") else None,
            reopened_from=case_id,
            reopen_reason=reason,
        )

    def storm_safe_queue(self, tenant_code: Optional[str] = None, limit: int = 100) -> list[dict]:
        """INC-2502: order by regulatory deadline so genuine cases aren't starved."""
        return self.store.queue(tenant_code=tenant_code, open_only=True, limit=limit)
