"""Case state machine, human sign-off and deadline-ordered queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from kestrel.domain import ACTIONABLE, CaseState, Disposition, TransitionError
from kestrel.exceptions import StaleEvidenceError
from kestrel.storage.bitemporal import BitemporalStore
from kestrel.storage.evidence import EvidenceStore
from kestrel.utils import parse_datetime, utc_now

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


class CaseLifecycle:
    """Case state machine with sign, reopen, and regulatory-deadline priority queue."""

    def __init__(self, store: BitemporalStore, evidence: EvidenceStore) -> None:
        """Bind lifecycle operations to a BitemporalStore."""
        self.store = store
        self.evidence = evidence

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
    ) -> dict[str, Any]:
        """Create a case from an adjudication recommendation and persist it."""
        now = utc_now()
        # Priority: reportable with nearer deadline sorts first via store queue
        priority = 100.0 if regulator_reportable else 10.0
        if recommendation == Disposition.HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED:
            state = CaseState.PENDING_EVIDENCE
        elif recommendation == Disposition.AUTO_CLOSE:
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

    def transition(self, case_id: str, new_state: CaseState, **patch) -> dict[str, Any]:
        """Apply an ALLOWED state transition (optional field patches)."""
        if new_state == CaseState.CLOSED_SIGNED:
            raise TransitionError("use sign() for hash-bound human closure")
        case = self.store.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        if (
            new_state == CaseState.CLOSED_AUTO
            and case.get("recommendation") == Disposition.HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED
        ):
            raise TransitionError("unverified historical candidate cannot close automatically")
        cur = CaseState(case["state"])
        if new_state not in ALLOWED.get(cur, set()):
            raise TransitionError(f"{cur.value} -> {new_state.value} not allowed")
        case["state"] = new_state.value
        case["updated_at"] = utc_now().isoformat(sep=" ")
        case.update({k: v for k, v in patch.items() if v is not None})
        self.store.save_case(case)
        return case

    def sign(
        self,
        case_id: str,
        signed_by: str,
        disposition: Disposition,
        *,
        reason: Optional[str] = None,
        bundle_hash: Optional[str] = None,
        current_bundle_hash: Optional[str] = None,
    ) -> dict[str, Any]:
        """Human-sign a disposition and move the case to CLOSED_SIGNED.

        A named signer and viewed hash are mandatory. The hash must equal the
        case's sealed bundle hash, so a signature can never attach to evidence
        the reviewer did not see.
        """
        if disposition == Disposition.HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED:
            raise TransitionError("historical candidate is an unresolved review state, not a final disposition")
        signer = (signed_by or "").strip()
        if not signer:
            raise ValueError("a named human signer is required")
        if not bundle_hash or not bundle_hash.strip():
            raise StaleEvidenceError("the viewed evidence hash is required")
        case = self.store.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        if CaseState.CLOSED_SIGNED not in ALLOWED.get(CaseState(case["state"]), set()):
            raise TransitionError("case is not awaiting a signature")
        if not case.get("evidence_bundle_id"):
            raise StaleEvidenceError("case has no sealed evidence")
        try:
            doc = self.evidence.get(case["evidence_bundle_id"], tenant_code=case["tenant_code"])
        except (FileNotFoundError, PermissionError, OSError, ValueError) as exc:
            raise StaleEvidenceError("sealed evidence unavailable; cannot sign") from exc
        # Do not trust a caller-supplied current hash; verify the actual artifact.
        meta = self.store.get_evidence_meta(doc["bundle_id"], tenant_code=case["tenant_code"])
        if (
            not self.evidence.verify_document(doc)
            or not meta
            or doc["content_hash"] != meta["content_hash"]
            or doc["content_hash"] != bundle_hash.strip()
        ):
            raise StaleEvidenceError("evidence changed since it was viewed; reload before signing")
        if current_bundle_hash is not None and current_bundle_hash != doc["content_hash"]:
            raise StaleEvidenceError("current evidence hash mismatch")
        signoff = {
            "status": "SIGNED",
            "signed_by": signer,
            "signed_at": utc_now().isoformat(sep=" "),
            "disposition": disposition.value,
            "reason": (reason or "").strip(),
            "signed_bundle_hash": doc["content_hash"],
            "signed_bundle_id": doc["bundle_id"],
        }
        signed_bundle = self.evidence.write_bundle(
            tenant_code=case["tenant_code"],
            event_id=case["event_id"],
            case_id=case_id,
            recommendation=doc["recommendation"],
            inputs=doc["inputs"],
            reasoning_steps=doc["reasoning_steps"],
            rule_pack_version=doc["rule_pack_version"],
            ref_snapshot_id=doc["ref_snapshot_id"],
            code_version=doc["code_version"],
            reviewer_signoff=signoff,
        )
        case.update(
            state=CaseState.CLOSED_SIGNED.value,
            final_disposition=disposition.value,
            signed_by=signer,
            signed_at=signoff["signed_at"],
            updated_at=signoff["signed_at"],
            sign_reason=signoff["reason"],
            signed_bundle_hash=doc["content_hash"],
            signature_bundle_id=signed_bundle["bundle_id"],
        )
        self.store.save_case(case)
        return case

    def reopen(self, case_id: str, reason: str) -> dict[str, Any]:
        """Reopen months later — new case revision linked to prior."""
        prior = self.store.get_case(case_id)
        if not prior:
            raise KeyError(case_id)
        self.transition(case_id, CaseState.REOPENED, reopen_reason=reason)
        return self.create(
            event_id=prior["event_id"],
            tenant_code=prior["tenant_code"],
            reg_deadline_utc=parse_datetime(prior.get("reg_deadline_utc")),
            regulator_reportable=bool(prior.get("regulator_reportable")),
            recommendation=Disposition(prior["recommendation"]) if prior.get("recommendation") else None,
            evidence_bundle_id=prior.get("evidence_bundle_id"),
            reopened_from=case_id,
            reopen_reason=reason,
        )

    def storm_safe_queue(self, tenant_code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """Order stored cases by deadline; no admission/fairness or paging guarantee."""
        return self.store.queue(tenant_code=tenant_code, open_only=True, limit=limit)
