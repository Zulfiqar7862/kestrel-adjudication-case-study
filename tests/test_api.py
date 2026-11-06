"""REST API and reviewer dashboard."""

from __future__ import annotations

import unittest
from typing import Any

from kestrel.api.app import _http_request, create_app
from kestrel.engine import RELEASE_WITH_NOTE
from kestrel.exceptions import DependencyMissingError
from tests._base import _KestrelTestCase


class TestAPISmoke(_KestrelTestCase):
    """In-process FastAPI TestClient smoke tests (skip if httpx/fastapi missing)."""

    def _req(self, *args: Any, **kwargs: Any) -> tuple[int, Any]:
        """Wrap _http_request and skip the test when FastAPI/httpx are absent."""
        try:
            return _http_request(*args, **kwargs)
        except (RuntimeError, DependencyMissingError) as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def test_api_health_adjudicate_basis(self) -> None:
        """Exercise /health, /adjudicate, /evidence/basis, cross-tenant 403, /replay."""
        code, health = self._req("GET", "/health", self.svc)
        self.assertEqual(code, 200)
        self.assertTrue(health["ok"])
        code, body = self._req("POST", "/adjudicate", self.svc, {"event_id": "EXC-107133", "persist": True})
        self.assertEqual(code, 200)
        self.assertEqual(body["recommendation"], RELEASE_WITH_NOTE)
        bundle_id = body["bundle_id"]
        code, b = self._req(
            "POST",
            "/evidence/basis",
            self.svc,
            {"event_id": "EXC-107133", "tenant_code": "T-KAVERI"},
        )
        self.assertEqual(code, 200)
        self.assertGreaterEqual(b["retrieval_latency_ms"], 0)
        code, denied = self._req("GET", f"/evidence/{bundle_id}", self.svc, query={"tenant_code": "T-MERIDIAN"})
        self.assertEqual(code, 403)
        code, ok = self._req(
            "POST",
            "/replay",
            self.svc,
            {"bundle_id": bundle_id, "tenant_code": "T-KAVERI"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(ok["identical"])


class TestReviewerDashboard(_KestrelTestCase):
    """Reviewer dashboard page and the sign-off safeguards it relies on."""

    def _client(self) -> Any:
        """Return a TestClient or skip when FastAPI/httpx are absent."""
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(str(exc)) from exc
        return TestClient(create_app(self.svc))

    def test_ui_page_and_events(self) -> None:
        """/ui serves the four-step page; /events lists all 420 alerts."""
        c = self._client()
        page = c.get("/ui")
        self.assertEqual(page.status_code, 200)
        for marker in ("Kestrel Reviewer Dashboard", "1. Pick a case", "4. Sign the decision"):
            self.assertIn(marker, page.text)
        ev = c.get("/events").json()
        self.assertEqual(ev["count"], 420)
        self.assertEqual(ev["counts"]["AUTO_CLOSE"], 224)
        self.assertEqual(c.get("/events/EXC-107133").json()["recommendation"], RELEASE_WITH_NOTE)

    def test_sign_requires_named_signer_and_current_evidence(self) -> None:
        """Blank signer is 422, a stale evidence hash is 409, the viewed hash signs."""
        c = self._client()
        out = c.post("/adjudicate", json={"event_id": "EXC-107133", "persist": True}).json()
        case_id = out["case_id"]
        doc = c.get(f"/evidence/{out['bundle_id']}", params={"tenant_code": "T-KAVERI"}).json()
        blank = c.post(f"/cases/{case_id}/sign", params={"signed_by": "   ", "disposition": RELEASE_WITH_NOTE})
        self.assertEqual(blank.status_code, 422)
        stale = c.post(
            f"/cases/{case_id}/sign",
            params={"signed_by": "Priya Menon", "disposition": RELEASE_WITH_NOTE, "bundle_hash": "0" * 64},
        )
        self.assertEqual(stale.status_code, 409)
        ok = c.post(
            f"/cases/{case_id}/sign",
            params={"signed_by": "Priya Menon", "disposition": RELEASE_WITH_NOTE, "bundle_hash": doc["content_hash"]},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["signed_bundle_hash"], doc["content_hash"])
