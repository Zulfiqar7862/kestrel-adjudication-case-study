"""Hash-chained evidence: tamper detection, isolation, replay, latency."""

from __future__ import annotations

import json
from pathlib import Path

from tests._base import _KestrelTestCase


class TestEvidenceChain(_KestrelTestCase):
    """Evidence hash-chain, tamper detection, Cl.22 isolation, latency, replay."""

    def test_hash_chain_and_tamper_detection(self) -> None:
        """Chain verifies; flipping disposition to DESTROY fails verify_chain."""
        a = self.svc.adjudicate_event("EXC-107133", persist=True)
        tenant = a["result"].tenant_code
        b = self.svc.adjudicate_event("EXC-110287", persist=True)
        if b["result"].tenant_code != tenant:
            for e in self.svc.pack.events:  # type: ignore[union-attr]
                if e["tenant_code"] == tenant and e["event_id"] != "EXC-107133":
                    self.svc.adjudicate_event(e["event_id"], persist=True)
                    break
        chain = self.svc.verify_tenant_chain(tenant)
        self.assertTrue(chain["ok"])
        self.assertGreaterEqual(chain["length"], 1)
        meta = self.svc.store.evidence_for_event("EXC-107133", tenant)[0]
        path = Path(meta["path"])
        # This class shares a service: restore tampering before other tests read
        # the now fully verified tenant chain. Keep every tamper assertion.
        self.addCleanup(path.write_text, path.read_text(encoding="utf-8"), encoding="utf-8")
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["recommendation"]["disposition"] = "DESTROY"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        broken = self.svc.verify_tenant_chain(tenant)
        self.assertFalse(broken["ok"])
        self.assertTrue(any("tamper" in e or "hash" in e for e in broken["errors"]))

    def test_tenant_isolation_meridian_clause(self) -> None:
        """Foreign tenant cannot read T-KAVERI evidence (PermissionError)."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        bundle_id = out["bundle"]["bundle_id"]
        with self.assertRaises(PermissionError) as ctx:
            self.svc.evidence.get(bundle_id, tenant_code="T-PINNACLE")
        msg = str(ctx.exception).lower()
        self.assertTrue("tenant isolation" in msg or "cl.22" in msg or "belongs" in msg)

    def test_retrieval_latency_under_hour(self) -> None:
        """Full basis retrieval is far under the one-hour board commitment."""
        self.svc.adjudicate_event("EXC-107133", persist=True)
        basis = self.svc.full_basis("EXC-107133", "T-KAVERI")
        self.assertTrue(basis["within_one_hour"])
        self.assertLess(basis["retrieval_latency_ms"], 5_000)
        self.assertTrue(basis["retention_until"])

    def test_replay_determinism(self) -> None:
        """Replaying from bundle yields an identical disposition."""
        out = self.svc.adjudicate_event("EXC-107133", persist=True)
        replay = self.svc.replay_from_bundle(out["bundle"]["bundle_id"], "T-KAVERI")
        self.assertTrue(replay["identical"])
