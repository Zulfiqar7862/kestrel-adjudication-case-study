"""Immutable, append-only, hash-chained evidence bundles.

Each recommendation writes a content-addressed JSON document. Bundles for a
tenant form a hash chain (prev_hash). Tampering breaks verify_chain().
Tenant isolation: load/get require tenant_code and refuse cross-tenant reads.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from kestrel_sentinel.store.bitemporal import BitemporalStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class EvidenceStore:
    def __init__(
        self,
        root: Path | str,
        db: BitemporalStore,
        *,
        retention_years: int = 7,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.retention_years = retention_years

    def _tenant_dir(self, tenant_code: str) -> Path:
        d = self.root / tenant_code
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _last_hash(self, tenant_code: str) -> Optional[str]:
        chain = self.db.chain_for_tenant(tenant_code)
        return chain[-1]["content_hash"] if chain else None

    def write_bundle(
        self,
        *,
        tenant_code: str,
        event_id: str,
        recommendation: dict[str, Any],
        inputs: dict[str, Any],
        reasoning_steps: list[str],
        rule_pack_version: str,
        ref_snapshot_id: str,
        code_version: str,
        case_id: Optional[str] = None,
        reviewer_signoff: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        created = _utcnow()
        retention_until = created + timedelta(days=365 * self.retention_years + 2)  # leap cushion
        prev = self._last_hash(tenant_code)
        # Content-addressed core (hash excludes bundle_id/path/prev to allow chain link)
        core = {
            "tenant_code": tenant_code,
            "event_id": event_id,
            "case_id": case_id,
            "created_at": created.isoformat(sep=" "),
            "retention_until": retention_until.isoformat(sep=" "),
            "retention_years": self.retention_years,
            "rule_pack_version": rule_pack_version,
            "ref_snapshot_id": ref_snapshot_id,
            "code_version": code_version,
            "inputs": inputs,
            "recommendation": recommendation,
            "reasoning_steps": reasoning_steps,
            "reviewer_signoff": reviewer_signoff
            or {"status": "UNSIGNED", "signed_by": None, "signed_at": None},
        }
        content_hash = canonical_hash(core)
        bundle_id = f"EVB-{content_hash[:16]}"
        document = {
            **core,
            "bundle_id": bundle_id,
            "content_hash": content_hash,
            "prev_hash": prev,
            "schema": "kestrel.evidence.v1",
        }
        path = self._tenant_dir(tenant_code) / f"{bundle_id}.json"
        path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
        meta = {
            "bundle_id": bundle_id,
            "tenant_code": tenant_code,
            "event_id": event_id,
            "case_id": case_id,
            "content_hash": content_hash,
            "prev_hash": prev,
            "path": str(path),
            "created_at": created.isoformat(sep=" "),
            "retention_until": retention_until.isoformat(sep=" "),
            "rule_pack_version": rule_pack_version,
            "ref_snapshot_id": ref_snapshot_id,
            "code_version": code_version,
        }
        self.db.index_evidence(meta)
        return document

    def get(
        self,
        bundle_id: str,
        *,
        tenant_code: str,
        measure: bool = False,
    ) -> dict[str, Any]:
        """Retrieve full basis for a disposition. Enforces tenant isolation."""
        t0 = time.perf_counter()
        meta = self.db.get_evidence_meta(bundle_id, tenant_code=tenant_code)
        if not meta:
            # Distinguish missing vs cross-tenant
            any_meta = self.db.get_evidence_meta(bundle_id, tenant_code=None)
            if any_meta and any_meta["tenant_code"] != tenant_code:
                raise PermissionError(
                    f"tenant isolation: bundle {bundle_id} belongs to "
                    f"{any_meta['tenant_code']}, not {tenant_code} (Meridian Cl.22)"
                )
            raise FileNotFoundError(f"evidence bundle not found: {bundle_id}")
        path = Path(meta["path"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("tenant_code") != tenant_code:
            raise PermissionError("tenant isolation violation on disk document")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if measure:
            doc["_retrieval_latency_ms"] = elapsed_ms
        return doc

    def verify_document(self, doc: dict[str, Any]) -> bool:
        core = {
            k: doc[k]
            for k in (
                "tenant_code",
                "event_id",
                "case_id",
                "created_at",
                "retention_until",
                "retention_years",
                "rule_pack_version",
                "ref_snapshot_id",
                "code_version",
                "inputs",
                "recommendation",
                "reasoning_steps",
                "reviewer_signoff",
            )
            if k in doc
        }
        return canonical_hash(core) == doc.get("content_hash")

    def verify_chain(self, tenant_code: str) -> dict[str, Any]:
        chain = self.db.chain_for_tenant(tenant_code)
        errors: list[str] = []
        prev: Optional[str] = None
        for i, meta in enumerate(chain):
            doc = json.loads(Path(meta["path"]).read_text(encoding="utf-8"))
            if not self.verify_document(doc):
                errors.append(f"{meta['bundle_id']}: content hash mismatch (tamper)")
            expected_prev = prev
            if doc.get("prev_hash") != expected_prev:
                errors.append(
                    f"{meta['bundle_id']}: chain break at index {i}: "
                    f"prev_hash={doc.get('prev_hash')} expected={expected_prev}"
                )
            prev = doc.get("content_hash")
        return {
            "tenant_code": tenant_code,
            "length": len(chain),
            "ok": not errors,
            "errors": errors,
        }

    def produce_full_basis(
        self, event_id: str, tenant_code: str
    ) -> dict[str, Any]:
        """Board commitment 3: full basis on request — measure latency."""
        t0 = time.perf_counter()
        metas = self.db.evidence_for_event(event_id, tenant_code)
        if not metas:
            raise FileNotFoundError(f"no evidence for {event_id} under {tenant_code}")
        # Latest bundle
        meta = metas[-1]
        doc = self.get(meta["bundle_id"], tenant_code=tenant_code, measure=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "event_id": event_id,
            "tenant_code": tenant_code,
            "bundle": doc,
            "retrieval_latency_ms": elapsed_ms,
            "within_one_hour": elapsed_ms < 3_600_000,
            "retention_until": meta["retention_until"],
            "versions": {
                "rule_pack_version": meta["rule_pack_version"],
                "ref_snapshot_id": meta["ref_snapshot_id"],
                "code_version": meta["code_version"],
            },
        }
