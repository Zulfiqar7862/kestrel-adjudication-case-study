from fastapi.testclient import TestClient

from kestrel_sentinel.api.app import create_app


def test_api_health_adjudicate_basis(tmp_svc):
    app = create_app(tmp_svc)
    client = TestClient(app)
    assert client.get("/health").json()["ok"] is True
    r = client.post("/adjudicate", json={"event_id": "EXC-107133", "persist": True})
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"] == "RELEASE_WITH_NOTE"
    bundle_id = body["bundle_id"]
    b = client.post(
        "/evidence/basis",
        json={"event_id": "EXC-107133", "tenant_code": "T-KAVERI"},
    )
    assert b.status_code == 200
    assert b.json()["retrieval_latency_ms"] >= 0
    # cross-tenant forbidden
    denied = client.get(f"/evidence/{bundle_id}", params={"tenant_code": "T-MERIDIAN"})
    assert denied.status_code == 403
    ok = client.post("/replay", json={"bundle_id": bundle_id, "tenant_code": "T-KAVERI"})
    assert ok.status_code == 200
    assert ok.json()["identical"] is True
