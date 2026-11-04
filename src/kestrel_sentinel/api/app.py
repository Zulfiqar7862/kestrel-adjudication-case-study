from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from kestrel_sentinel.service import AdjudicationService


class AdjudicateRequest(BaseModel):
    event_id: str
    persist: bool = True


class BasisRequest(BaseModel):
    event_id: str
    tenant_code: str


class ReplayRequest(BaseModel):
    bundle_id: str
    tenant_code: str


class VerifyRequest(BaseModel):
    tenant_code: str


def create_app(svc: Optional[AdjudicationService] = None) -> FastAPI:
    service = svc or AdjudicationService()
    if service.engine is None:
        service.bootstrap()

    app = FastAPI(title="Kestrel Sentinel Adjudication API", version="0.2.0")
    app.state.svc = service

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "snapshot_id": service.snapshot_id,
            "rule_pack_version": service.settings.rule_pack_version,
        }

    @app.post("/adjudicate")
    def adjudicate(body: AdjudicateRequest) -> dict[str, Any]:
        try:
            out = service.adjudicate_event(body.event_id, persist=body.persist)
        except KeyError:
            raise HTTPException(404, f"unknown event {body.event_id}") from None
        r = out["result"]
        return {
            "event_id": r.event_id,
            "tenant_code": r.tenant_code,
            "recommendation": r.recommendation,
            "confidence": r.confidence,
            "rationale": r.rationale,
            "bundle_id": (out["bundle"] or {}).get("bundle_id"),
            "case_id": (out["case"] or {}).get("case_id"),
            "reg_deadline_utc": r.reg_deadline_utc,
        }

    @app.post("/evidence/basis")
    def basis(body: BasisRequest) -> dict[str, Any]:
        try:
            return service.full_basis(body.event_id, body.tenant_code)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/evidence/{bundle_id}")
    def get_evidence(bundle_id: str, tenant_code: str) -> dict[str, Any]:
        try:
            return service.evidence.get(bundle_id, tenant_code=tenant_code, measure=True)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/evidence/verify")
    def verify(body: VerifyRequest) -> dict[str, Any]:
        return service.verify_tenant_chain(body.tenant_code)

    @app.post("/replay")
    def replay(body: ReplayRequest) -> dict[str, Any]:
        try:
            return service.replay_from_bundle(body.bundle_id, body.tenant_code)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/shadow/bulletin")
    def shadow() -> dict[str, Any]:
        report = service.shadow_bulletin()
        # trim for API response size
        return {
            "change": report["change"],
            "candidates": report["candidates"],
            "diffs": report["diffs"],
            "sample_diffs": report["diff_rows"][:20],
            "rao_gate": report["rao_gate"],
        }

    @app.get("/queue")
    def queue(tenant_code: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        return {"items": service.lifecycle.storm_safe_queue(tenant_code=tenant_code, limit=limit)}

    @app.get("/as-of/sop")
    def as_of_sop(tenant_code: str, date: str) -> dict[str, Any]:
        return service.as_of_sop(tenant_code, date)

    return app
