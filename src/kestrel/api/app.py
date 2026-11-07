"""FastAPI application factory (REST API + reviewer dashboard)."""

from __future__ import annotations

import logging
from importlib import resources
from typing import Any, Optional

from kestrel.domain import Disposition, TransitionError
from kestrel.exceptions import (
    DependencyMissingError,
    NotFoundError,
    StaleEvidenceError,
    TenantIsolationError,
    ValidationAppError,
)
from kestrel.service import AdjudicationService

AdjudicateRequest: Any = None


BasisRequest: Any = None


VerifyRequest: Any = None


ReplayRequest: Any = None


HealthResponse: Any = None


def _load_api_models() -> None:
    """Lazily define Pydantic v2 request/response models in module globals."""
    global AdjudicateRequest, BasisRequest, VerifyRequest, ReplayRequest, HealthResponse
    if AdjudicateRequest is not None:
        return
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover
        raise DependencyMissingError(
            "API layer requires: pip install fastapi pydantic uvicorn  (engine/CLI/tests still run with only openpyxl)"
        ) from exc

    class _AdjudicateRequest(BaseModel):
        """POST /adjudicate body."""

        event_id: str = Field(..., min_length=1)
        persist: bool = True

    class _BasisRequest(BaseModel):
        """POST /evidence/basis body."""

        event_id: str = Field(..., min_length=1)
        tenant_code: str = Field(..., min_length=1)

    class _VerifyRequest(BaseModel):
        """POST /evidence/verify body."""

        tenant_code: str = Field(..., min_length=1)

    class _ReplayRequest(BaseModel):
        """POST /replay body."""

        bundle_id: str = Field(..., min_length=1)
        tenant_code: str = Field(..., min_length=1)

    class _HealthResponse(BaseModel):
        """GET /health payload."""

        ok: bool
        snapshot_id: Optional[str] = None
        rule_pack_version: str

    AdjudicateRequest = _AdjudicateRequest
    BasisRequest = _BasisRequest
    VerifyRequest = _VerifyRequest
    ReplayRequest = _ReplayRequest
    HealthResponse = _HealthResponse


def _require_fastapi() -> tuple[Any, Any, Any]:
    """Import FastAPI stack or raise a clear DependencyMissingError."""
    try:
        from fastapi import Depends, FastAPI, HTTPException, Query, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - depends on env
        raise DependencyMissingError(
            "API layer requires: pip install fastapi pydantic uvicorn  (engine/CLI/tests still run with only openpyxl)"
        ) from exc
    _load_api_models()
    return FastAPI, HTTPException, (Depends, Query, Request, JSONResponse)


def _reviewer_ui_html() -> str:
    """Load the single-page reviewer dashboard shipped with the package."""
    return (resources.files("kestrel.api") / "static" / "index.html").read_text(encoding="utf-8")


def create_app(svc: Optional[AdjudicationService] = None) -> Any:
    """Build a FastAPI application with DI-held AdjudicationService and typed routes.

    Lazy-imports FastAPI/Pydantic. Returns the app instance (not a server).
    """
    FastAPI, HTTPException, extras = _require_fastapi()
    Depends, Query, Request, JSONResponse = extras

    service = svc or AdjudicationService()
    if service.engine is None:
        service.bootstrap()

    app = FastAPI(
        title="Kestrel Sentinel Adjudication API",
        version=service.settings.code_version,
        description="As-of adjudication, evidence basis, shadow replay, queue.",
    )
    app.state.svc = service

    def get_svc() -> AdjudicationService:
        """FastAPI dependency: shared AdjudicationService."""
        return app.state.svc

    @app.exception_handler(TenantIsolationError)
    async def _tenant_exc(_request: Request, exc: TenantIsolationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(PermissionError)
    async def _perm_exc(_request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _nf_exc(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def _fnf_exc(_request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(KeyError)
    async def _key_exc(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": f"unknown entity {exc}"})

    @app.exception_handler(ValidationAppError)
    async def _val_exc(_request: Request, exc: ValidationAppError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/health", response_model=HealthResponse)
    def health(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Liveness + rule-pack identity."""
        return {
            "ok": True,
            "snapshot_id": svc_dep.snapshot_id,
            "rule_pack_version": svc_dep.settings.rule_pack_version,
        }

    @app.post("/adjudicate")
    def adjudicate(
        payload: AdjudicateRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Adjudicate one event and optionally persist evidence + case."""
        try:
            out = svc_dep.adjudicate_event(payload.event_id, persist=payload.persist)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown event {payload.event_id}") from exc
        result = out["result"]
        case = out.get("case") or {}
        return {
            "event_id": result.event_id,
            "tenant_code": result.tenant_code,
            "recommendation": result.recommendation,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "requires_human_signature": result.requires_human_signature,
            "bundle_id": (out["bundle"] or {}).get("bundle_id"),
            "case_id": case.get("case_id"),
            "case_state": case.get("state"),
            "reg_deadline_utc": result.reg_deadline_utc,
        }

    @app.post("/cases/{case_id}/sign")
    def sign_case(
        case_id: str,
        signed_by: str = Query(..., min_length=1),
        disposition: str = Query(..., min_length=1),
        reason: Optional[str] = Query(None),
        bundle_hash: str = Query(..., min_length=1, description="content_hash the reviewer viewed"),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Lifecycle: named human sign-off, bound to the mandatory viewed evidence hash."""
        if not signed_by.strip():
            raise HTTPException(status_code=422, detail="a named human signer is required")
        case = svc_dep.store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}")
        current_hash: Optional[str] = None
        if case.get("evidence_bundle_id"):
            try:
                doc = svc_dep.evidence.get(case["evidence_bundle_id"], tenant_code=case["tenant_code"])
                current_hash = doc.get("content_hash")
            except (FileNotFoundError, PermissionError):
                current_hash = None
        try:
            disp = Disposition(disposition)
            return svc_dep.lifecycle.sign(
                case_id,
                signed_by=signed_by,
                disposition=disp,
                reason=reason,
                bundle_hash=bundle_hash,
                current_bundle_hash=current_hash,
            )
        except StaleEvidenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}") from exc
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/cases/{case_id}/reopen")
    def reopen_case(
        case_id: str,
        reason: str = Query("reopened", min_length=1),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Lifecycle: reopen a closed case (bulletin / customer / audit)."""
        try:
            case = svc_dep.lifecycle.reopen(case_id, reason=reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}") from exc
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return case

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Fetch one case record."""
        case = svc_dep.store.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail=f"unknown case {case_id}")
        return case

    @app.get("/evidence/{bundle_id}")
    def get_evidence(
        bundle_id: str,
        tenant_code: str = Query(...),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Fetch one evidence bundle with tenant isolation."""
        try:
            return svc_dep.evidence.get(bundle_id, tenant_code=tenant_code, measure=True)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evidence/basis")
    def evidence_basis(
        payload: BasisRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Board commitment 3 — full reconstructable basis."""
        try:
            return svc_dep.full_basis(payload.event_id, payload.tenant_code)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/evidence/verify")
    def evidence_verify(
        payload: VerifyRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Verify per-tenant evidence hash chain."""
        return svc_dep.verify_tenant_chain(payload.tenant_code)

    @app.post("/replay")
    def replay(
        payload: ReplayRequest,  # type: ignore[valid-type]
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Replay adjudication from a stored bundle."""
        try:
            return svc_dep.replay_from_bundle(payload.bundle_id, payload.tenant_code)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/shadow/bulletin")
    def shadow_bulletin(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Dr Rao gate — TT-CB-114 shadow diff summary."""
        report = svc_dep.shadow_bulletin()
        return {
            "change": report["change"],
            "candidates": report["candidates"],
            "diffs": report["diffs"],
            "sample_diffs": report["diff_rows"][:20],
            "rao_gate": report["rao_gate"],
        }

    @app.get("/queue")
    def queue(
        tenant_code: Optional[str] = Query(None),
        limit: int = Query(20, ge=1, le=500),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """Storm-safe priority queue ordered by regulatory deadline."""
        return {"items": svc_dep.lifecycle.storm_safe_queue(tenant_code=tenant_code, limit=limit)}

    @app.get("/as-of/sop")
    def as_of_sop(
        tenant_code: str = Query(...),
        date: str = Query(..., description="YYYY-MM-DD"),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """SOP in force as-at a date (AUD-2603 shape)."""
        return svc_dep.as_of_sop(tenant_code, date)

    @app.get("/ops/health-report")
    def ops_health_report(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Full 3am monitoring catalog (same payload as CLI `health`)."""
        return svc_dep.health_report()

    @app.get("/ops/agreement")
    def ops_agreement(svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Agreement stratification (same payload as CLI `agreement`)."""
        return svc_dep.agreement_report()

    def _events_cache(svc_dep: AdjudicationService) -> list[dict[str, Any]]:
        """Adjudicate every pack event once (read-only, no persistence) for the dashboard."""
        cached = getattr(app.state, "events_cache", None)
        if cached is not None and cached[0] == svc_dep.snapshot_id:
            return cached[1]
        rows: list[dict[str, Any]] = []
        assert svc_dep.engine and svc_dep.pack
        for event in svc_dep.pack.events:
            result = svc_dep.engine.adjudicate(event)
            rows.append(
                {
                    "event_id": result.event_id,
                    "tenant_code": result.tenant_code,
                    "recommendation": result.recommendation,
                    "requires_human_signature": result.requires_human_signature,
                    "confidence": result.confidence,
                    "triage_label": result.triage_label,
                    "raw_max_temp_c": event.get("max_temp_c"),
                    "reported_max_temp_c": result.reported_max_temp_c,
                    "scenarios": result.evidence.get("temps", {}).get("uncertainty"),
                    "bulletin_applied": result.bulletin_applied,
                    "logger_fw": event.get("logger_fw"),
                    "regulator_reportable": result.regulator_reportable,
                    "reg_window_hours": result.reg_window_hours,
                    "reg_deadline_utc": result.reg_deadline_utc,
                    "alert_ts_utc": str(event.get("alert_ts_utc")),
                }
            )
        rows.sort(key=lambda row: (row["reg_deadline_utc"] or "9999", row["event_id"]))
        app.state.events_cache = (svc_dep.snapshot_id, rows)
        return rows

    @app.get("/events")
    def list_events(
        tenant_code: Optional[str] = Query(None),
        svc_dep: AdjudicationService = Depends(get_svc),
    ) -> dict[str, Any]:
        """All pack events with the deterministic recommendation, ordered by regulatory deadline."""
        rows = _events_cache(svc_dep)
        if tenant_code:
            rows = [row for row in rows if row["tenant_code"] == tenant_code]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["recommendation"]] = counts.get(row["recommendation"], 0) + 1
        return {"count": len(rows), "counts": counts, "items": rows}

    @app.get("/events/{event_id}")
    def event_detail(event_id: str, svc_dep: AdjudicationService = Depends(get_svc)) -> dict[str, Any]:
        """Read-only adjudication of one event: facts, uncertainty scenarios, as-of basis and rule trace."""
        assert svc_dep.engine and svc_dep.pack
        event = svc_dep.pack.event_by_id(event_id)
        if not event:
            raise HTTPException(status_code=404, detail=f"unknown event {event_id}")
        result = svc_dep.engine.adjudicate(event)
        return {
            "event_id": result.event_id,
            "tenant_code": result.tenant_code,
            "recommendation": result.recommendation,
            "requires_human_signature": result.requires_human_signature,
            "confidence": result.confidence,
            "triage_label": result.triage_label,
            "rationale": list(result.rationale),
            "alert": {
                "alert_ts_utc": str(event.get("alert_ts_utc")),
                "excursion_start_utc": str(event.get("excursion_start_utc")),
                "min_temp_c": event.get("min_temp_c"),
                "max_temp_c": event.get("max_temp_c"),
                "duration_min": event.get("duration_min"),
                "logger_id": event.get("logger_id"),
                "logger_fw": event.get("logger_fw"),
                "lane_text": event.get("lane_text"),
                "carrier_ref_as_received": event.get("carrier_ref_as_received"),
                "product_ref_as_received": event.get("product_ref_as_received"),
                "prior_excursions_lane_90d": event.get("prior_excursions_lane_90d"),
            },
            "uncertainty": {
                "bulletin": "TT-CB-114",
                "applies_to_fw": "TT-2.14.3",
                "applied": result.bulletin_applied,
                "raw_max_temp_c": event.get("max_temp_c"),
                "reported_max_temp_c": result.reported_max_temp_c,
                "scenarios": result.evidence.get("temps", {}).get("uncertainty"),
            },
            "basis": {
                "product_sku": result.product_sku,
                "product_brand": result.product_brand,
                "product_match_method": result.product_match_method,
                "stability_study_ref": result.stability_study_ref,
                "sop_doc_id": result.sop_doc_id,
                "sop_revision": result.sop_revision,
                "sop_overlap_conflict": result.sop_overlap_conflict,
                "carrier_contract_id": result.carrier_contract_id,
                "carrier_has_cold_chain_clause": result.carrier_has_cold_chain_clause,
            },
            "regulatory": {
                "reportable": result.regulator_reportable,
                "window_hours": result.reg_window_hours,
                "deadline_utc": result.reg_deadline_utc,
            },
            "historical": {
                "final_disposition": result.historical_final_disposition,
                "assistant_recommendation": result.historical_recommendation,
            },
        }

    from fastapi.responses import HTMLResponse, RedirectResponse

    @app.get("/", include_in_schema=False)
    def root() -> Any:
        """Send browsers to the reviewer dashboard."""
        return RedirectResponse(url="/ui")

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    def reviewer_ui() -> Any:
        """Reviewer dashboard: queue, case, evidence, sign (inline, no external assets)."""
        return HTMLResponse(_reviewer_ui_html())

    return app


def serve_http(
    svc: AdjudicationService,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Serve the FastAPI app with uvicorn (lazy import)."""
    if svc.engine is None:
        svc.bootstrap()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise DependencyMissingError("serve requires: pip install fastapi pydantic uvicorn") from exc
    app = create_app(svc)
    logging.getLogger("kestrel.http").info("serving on http://%s:%s (uvicorn/FastAPI)", host, port)
    uvicorn.run(app, host=host, port=port, log_level=svc.settings.log_level.lower())


def _http_request(
    method: str,
    path: str,
    svc: AdjudicationService,
    body: Optional[dict[str, Any]] = None,
    query: Optional[dict[str, str]] = None,
) -> tuple[int, Any]:
    """In-process API helper via FastAPI TestClient when httpx is available."""
    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI TestClient unavailable — pip install fastapi pydantic httpx") from exc
    app = create_app(svc)
    client = TestClient(app)
    if method.upper() == "GET":
        resp = client.get(path, params=query or None)
    else:
        resp = client.post(path, json=body or {})
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": resp.text}
    if resp.status_code >= 400 and isinstance(payload, dict) and "detail" in payload and "error" not in payload:
        detail = payload["detail"]
        payload = {"error": detail if isinstance(detail, str) else str(detail)}
    return resp.status_code, payload
