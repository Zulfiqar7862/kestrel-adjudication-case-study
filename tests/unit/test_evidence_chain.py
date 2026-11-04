import json
from pathlib import Path


def test_hash_chain_and_tamper_detection(tmp_svc):
    a = tmp_svc.adjudicate_event("EXC-107133", persist=True)
    # second event same tenant if possible, else another
    b = tmp_svc.adjudicate_event("EXC-110287", persist=True)
    tenant = a["result"].tenant_code
    # EXC-110287 is T-KAVERI? check — if different tenants, adjudicate another Kaveri
    if b["result"].tenant_code != tenant:
        # find another Kaveri event
        for e in tmp_svc.pack.events:
            if e["tenant_code"] == tenant and e["event_id"] != "EXC-107133":
                b = tmp_svc.adjudicate_event(e["event_id"], persist=True)
                break
    chain = tmp_svc.verify_tenant_chain(tenant)
    assert chain["ok"] is True
    assert chain["length"] >= 1

    # Tamper with first bundle file
    meta = tmp_svc.store.evidence_for_event("EXC-107133", tenant)[0]
    path = Path(meta["path"])
    doc = json.loads(path.read_text())
    doc["recommendation"]["disposition"] = "DESTROY"
    path.write_text(json.dumps(doc, indent=2))
    broken = tmp_svc.verify_tenant_chain(tenant)
    assert broken["ok"] is False
    assert any("tamper" in e or "hash" in e for e in broken["errors"])


def test_tenant_isolation_meridian_clause(tmp_svc):
    out = tmp_svc.adjudicate_event("EXC-107133", persist=True)
    bundle_id = out["bundle"]["bundle_id"]
    # Pinnacle must not read Kaveri evidence
    try:
        tmp_svc.evidence.get(bundle_id, tenant_code="T-PINNACLE")
        assert False, "should have raised"
    except PermissionError as e:
        assert "tenant isolation" in str(e).lower() or "Cl.22" in str(e) or "belongs" in str(e)


def test_retrieval_latency_under_hour(tmp_svc):
    tmp_svc.adjudicate_event("EXC-107133", persist=True)
    basis = tmp_svc.full_basis("EXC-107133", "T-KAVERI")
    assert basis["within_one_hour"] is True
    assert basis["retrieval_latency_ms"] < 5_000  # generous local bound
    assert basis["retention_until"]


def test_replay_determinism(tmp_svc):
    out = tmp_svc.adjudicate_event("EXC-107133", persist=True)
    replay = tmp_svc.replay_from_bundle(out["bundle"]["bundle_id"], "T-KAVERI")
    assert replay["identical"] is True
