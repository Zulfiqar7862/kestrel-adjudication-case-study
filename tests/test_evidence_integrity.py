"""File/index reconciliation and fail-closed evidence consumers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kestrel.api.app import create_app
from kestrel.cli import _cmd_verify
from kestrel.domain import Disposition
from kestrel.lifecycle import StaleEvidenceError
from kestrel.storage.bitemporal import BitemporalStore
from kestrel.storage.evidence import EvidenceStore, canonical_hash
from tests._base import _make_tmp_svc


def reseal(path):
    doc = json.loads(path.read_text())
    doc["reasoning_steps"].append("altered reasoning")
    core = {k: v for k, v in doc.items() if k not in {"bundle_id", "content_hash", "prev_hash", "schema"}}
    doc["content_hash"] = canonical_hash(core)
    path.write_text(json.dumps(doc))
    return doc


@pytest.fixture
def chain(tmp_path):
    db = BitemporalStore(tmp_path / "index.sqlite")
    evidence = EvidenceStore(tmp_path / "evidence", db)
    docs = [
        evidence.write_bundle(
            tenant_code="T-A",
            event_id=f"E-{i}",
            recommendation={},
            inputs={},
            reasoning_steps=["original"],
            rule_pack_version="test",
            ref_snapshot_id="test",
            code_version="test",
        )
        for i in range(3)
    ]
    metas = db.chain_for_tenant("T-A")
    assert evidence.verify_chain("T-A")["ok"]
    return evidence, db, docs, [Path(m["path"]) for m in metas]


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("resealed_tail", "INDEX_HASH_MISMATCH"),
        ("resealed_middle", "INDEX_HASH_MISMATCH"),
        ("deleted_tail", "MISSING_FILE"),
        ("swapped_files", "INDEX_METADATA_MISMATCH:bundle_id"),
        ("index_hash", "INDEX_HASH_MISMATCH"),
        ("index_predecessor", "INDEX_PREDECESSOR_MISMATCH"),
        ("file_predecessor", "FILE_PREDECESSOR_MISMATCH"),
        ("index_without_file", "MISSING_FILE"),
        ("file_without_index", "UNINDEXED_FILE"),
        ("cross_tenant_path", "PATH_MISMATCH"),
        ("cross_tenant_document", "INDEX_METADATA_MISMATCH:tenant_code"),
        ("malformed_json", "UNREADABLE_FILE"),
    ],
)
def test_chain_reconciles_both_stores(chain, damage, reason):
    evidence, db, docs, paths = chain
    tail = docs[-1]["bundle_id"]
    if damage.startswith("resealed_"):
        changed = reseal(paths[-1 if damage == "resealed_tail" else 1])
        if damage == "resealed_middle":
            successor = docs[-1]
            successor["prev_hash"] = changed["content_hash"]
            paths[-1].write_text(json.dumps(successor))
    elif damage == "deleted_tail":
        paths[-1].unlink()
    elif damage == "swapped_files":
        a, b = paths[0].read_bytes(), paths[-1].read_bytes()
        paths[0].write_bytes(b)
        paths[-1].write_bytes(a)
    elif damage in {"index_hash", "index_predecessor"}:
        field = "content_hash" if damage == "index_hash" else "prev_hash"
        with db.connection() as conn:
            conn.execute(f"UPDATE evidence_index SET {field}=? WHERE bundle_id=?", ("0" * 64, tail))
    elif damage == "file_predecessor":
        doc = docs[-1]
        doc["prev_hash"] = "0" * 64
        paths[-1].write_text(json.dumps(doc))
    elif damage == "index_without_file":
        paths[1].unlink()
    elif damage == "file_without_index":
        with db.connection() as conn:
            conn.execute("DELETE FROM evidence_index WHERE bundle_id=?", (tail,))
    elif damage == "cross_tenant_path":
        other = evidence.root / "T-B" / paths[-1].name
        other.parent.mkdir()
        paths[-1].rename(other)
        with db.connection() as conn:
            conn.execute("UPDATE evidence_index SET path=? WHERE bundle_id=?", (str(other), tail))
    elif damage == "cross_tenant_document":
        doc = docs[-1]
        doc["tenant_code"] = "T-B"
        paths[-1].write_text(json.dumps(doc))
        reseal(paths[-1])
    elif damage == "malformed_json":
        paths[-1].write_text("{broken")
    report = evidence.verify_chain("T-A")
    assert not report["ok"], report
    assert any(reason in error for error in report["errors"]), report


@pytest.fixture
def service(tmp_path):
    return _make_tmp_svc(tmp_path)


@pytest.mark.parametrize("consumer", ["get", "basis", "replay", "sign"])
def test_resealed_ancestor_blocks_consumers(service, consumer):
    first = service.adjudicate_event("EXC-107133", persist=True)
    second = service.adjudicate_event("EXC-107133", persist=True)
    meta = service.store.get_evidence_meta(first["bundle"]["bundle_id"])
    reseal(Path(meta["path"]))
    bundle = second["bundle"]
    tenant = bundle["tenant_code"]
    if consumer == "sign":
        with pytest.raises(StaleEvidenceError):
            service.lifecycle.sign(
                second["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=bundle["content_hash"]
            )
        assert service.store.get_case(second["case"]["case_id"])["state"] != "CLOSED_SIGNED"
    else:
        with pytest.raises(ValueError, match="INDEX_HASH_MISMATCH"):
            if consumer == "get":
                service.evidence.get(bundle["bundle_id"], tenant_code=tenant)
            elif consumer == "basis":
                service.full_basis("EXC-107133", tenant)
            else:
                service.replay_from_bundle(bundle["bundle_id"], tenant)


def test_cli_verify_fails_closed(chain, capsys):
    evidence, _, _, paths = chain
    reseal(paths[-1])

    class Service:
        verify_tenant_chain = evidence.verify_chain

    status = _cmd_verify(Service(), argparse.Namespace(tenant="T-A"))
    output = json.loads(capsys.readouterr().out)
    assert status == 1
    assert not output["ok"]
    assert any("INDEX_HASH_MISMATCH" in e for e in output["errors"])


def test_api_verify_reports_missing_file(service):
    out = service.adjudicate_event("EXC-107133", persist=True)
    meta = service.store.get_evidence_meta(out["bundle"]["bundle_id"])
    Path(meta["path"]).unlink()
    response = TestClient(create_app(service)).post("/evidence/verify", json={"tenant_code": "T-KAVERI"})
    assert response.status_code == 200
    assert not response.json()["ok"]
    assert any("MISSING_FILE" in e for e in response.json()["errors"])


@pytest.mark.parametrize("surface", ["get", "basis", "replay", "sign"])
def test_api_rejects_resealed_evidence(service, surface):
    out = service.adjudicate_event("EXC-107133", persist=True)
    bundle = out["bundle"]
    reseal(Path(service.store.get_evidence_meta(bundle["bundle_id"])["path"]))
    client = TestClient(create_app(service))
    if surface == "get":
        response = client.get(f"/evidence/{bundle['bundle_id']}", params={"tenant_code": "T-KAVERI"})
    elif surface == "basis":
        response = client.post("/evidence/basis", json={"event_id": "EXC-107133", "tenant_code": "T-KAVERI"})
    elif surface == "replay":
        response = client.post("/replay", json={"bundle_id": bundle["bundle_id"], "tenant_code": "T-KAVERI"})
    else:
        response = client.post(
            f"/cases/{out['case']['case_id']}/sign",
            params={"signed_by": "QA", "disposition": "RELEASE_WITH_NOTE", "bundle_hash": bundle["content_hash"]},
        )
    assert response.status_code == 409
    assert "INDEX_HASH_MISMATCH" in response.text


def test_unindexed_file_in_other_tenant_is_rejected(chain):
    evidence, _, _, paths = chain
    other = evidence.root / "T-B" / paths[-1].name
    other.parent.mkdir()
    other.write_bytes(paths[-1].read_bytes())
    report = evidence.verify_chain("T-B")
    assert not report["ok"], report
    assert any("UNINDEXED_FILE" in e for e in report["errors"])


def test_orphan_files_with_empty_index_fail_closed(chain):
    evidence, db, _, _ = chain
    with db.connection() as conn:
        conn.execute("DELETE FROM evidence_index")
    report = evidence.verify_chain("T-A")
    assert not report["ok"], report
    assert any("UNINDEXED_FILE" in e for e in report["errors"])


def test_sign_resealed_bundle_uses_shared_verification(service):
    out = service.adjudicate_event("EXC-107133", persist=True)
    bundle = out["bundle"]
    reseal(Path(service.store.get_evidence_meta(bundle["bundle_id"])["path"]))
    with pytest.raises(StaleEvidenceError, match="INDEX_HASH_MISMATCH"):
        service.lifecycle.sign(
            out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=bundle["content_hash"]
        )


@pytest.mark.parametrize("missing", ["prev_hash", "case_id"])
def test_explicit_null_metadata_cannot_be_omitted(chain, missing):
    evidence, _, docs, paths = chain
    doc = docs[0]
    del doc[missing]
    if missing == "case_id":
        core = {k: v for k, v in doc.items() if k not in {"bundle_id", "content_hash", "prev_hash", "schema"}}
        doc["content_hash"] = canonical_hash(core)
    paths[0].write_text(json.dumps(doc))
    report = evidence.verify_chain("T-A")
    assert any(f"MISSING_FIELD:{missing}" in e for e in report["errors"]), report
