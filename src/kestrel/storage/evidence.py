"""Per-tenant evidence with local file/index reconciliation and retention metadata."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from kestrel.storage.bitemporal import BitemporalStore
from kestrel.utils import utc_now

"""Locally hash-chained evidence bundles (not an independently anchored archive).

Each recommendation writes a content-addressed JSON document. Bundles for a
tenant form a hash chain (prev_hash). Verification reconciles files and SQLite;
an actor able to rewrite both stores is outside this local integrity guarantee.
Tenant isolation: load/get require tenant_code and refuse cross-tenant reads.
"""


_CORE_FIELDS = (
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


def canonical_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of a canonical JSON serialization of payload."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class EvidenceIntegrityError(ValueError):
    """Local evidence cannot be reconciled with its index and tenant chain."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__("evidence integrity verification failed: " + "; ".join(report["errors"]))


class EvidenceStore:
    """Per-tenant local file/index evidence store with retention metadata."""

    def __init__(
        self,
        root: Path | str,
        store: BitemporalStore,
        *,
        retention_years: int = 7,
    ) -> None:
        """Bind filesystem root and bitemporal DB index; create root directory."""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = store
        self.retention_years = retention_years

    def _tenant_dir(self, tenant_code: str) -> Path:
        """Return (and create) the per-tenant evidence directory."""
        tenant_dir = self.root / tenant_code
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir

    def _last_hash(self, tenant_code: str) -> Optional[str]:
        """Return the latest content hash in the tenant chain, or None if empty."""
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
        """Write a new evidence bundle, link prev_hash, and index metadata."""
        created = utc_now()
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
            "reviewer_signoff": reviewer_signoff or {"status": "UNSIGNED", "signed_by": None, "signed_at": None},
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
        started = time.perf_counter()
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
        report, documents = self._inspect_chain(tenant_code)
        if not report["ok"]:
            raise EvidenceIntegrityError(report)
        if bundle_id not in documents:
            raise EvidenceIntegrityError({**report, "ok": False, "errors": [f"{bundle_id}: INDEX_CHANGED"]})
        # Return the bytes parsed during verification, not a second unverified read.
        doc = documents[bundle_id]
        elapsed_ms = (time.perf_counter() - started) * 1000
        if measure:
            doc["_retrieval_latency_ms"] = elapsed_ms
        return doc

    def verify_document(self, doc: dict[str, Any]) -> bool:
        """Check self-consistency only; stored evidence also needs chain/index checks."""
        core = {k: doc[k] for k in _CORE_FIELDS if k in doc}
        return canonical_hash(core) == doc.get("content_hash")

    def _inspect_chain(self, tenant_code: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """Reconcile both stores; use indexed hashes, never file claims, as links.

        Read each document once so retrieval uses exactly the inspected contents.
        This is not a filesystem/SQLite transaction or an independent trust anchor.
        """
        chain = self.db.chain_for_tenant(tenant_code)
        errors: list[str] = []
        documents: dict[str, dict[str, Any]] = {}
        prev: Optional[str] = None
        tenant_dir = self.root.resolve() / tenant_code
        indexed_paths: set[Path] = set()
        valid_tenant = bool(tenant_code) and Path(tenant_code).name == tenant_code and tenant_code not in {".", ".."}
        if not valid_tenant:
            errors.append("INVALID_TENANT_PATH")
        else:
            for meta in chain:
                bundle_id = meta["bundle_id"]
                expected_path = tenant_dir / f"{bundle_id}.json"
                indexed_paths.add(expected_path)
                if meta["prev_hash"] != prev:
                    errors.append(f"{bundle_id}: INDEX_PREDECESSOR_MISMATCH")
                expected_prev = prev
                prev = meta["content_hash"]
                try:
                    path = Path(meta["path"])
                    if path.resolve() != expected_path or path.is_symlink():
                        errors.append(f"{bundle_id}: PATH_MISMATCH (expected tenant/bundle placement)")
                        continue
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    errors.append(f"{bundle_id}: MISSING_FILE")
                    continue
                except (OSError, ValueError, RuntimeError) as exc:
                    errors.append(f"{bundle_id}: UNREADABLE_FILE ({type(exc).__name__})")
                    continue
                if not isinstance(doc, dict):
                    errors.append(f"{bundle_id}: INVALID_DOCUMENT (expected object)")
                    continue
                for field in (*_CORE_FIELDS, "bundle_id", "content_hash", "prev_hash", "schema"):
                    if field not in doc:
                        errors.append(f"{bundle_id}: MISSING_FIELD:{field}")
                if not self.verify_document(doc):
                    errors.append(f"{bundle_id}: CONTENT_HASH_MISMATCH (tamper)")
                if doc.get("content_hash") != meta["content_hash"]:
                    errors.append(f"{bundle_id}: INDEX_HASH_MISMATCH")
                for field in (
                    "bundle_id",
                    "tenant_code",
                    "event_id",
                    "case_id",
                    "created_at",
                    "retention_until",
                    "rule_pack_version",
                    "ref_snapshot_id",
                    "code_version",
                ):
                    if doc.get(field) != meta[field]:
                        errors.append(f"{bundle_id}: INDEX_METADATA_MISMATCH:{field}")
                if doc.get("bundle_id") != f"EVB-{str(meta['content_hash'])[:16]}":
                    errors.append(f"{bundle_id}: CONTENT_ADDRESS_MISMATCH")
                if doc.get("schema") != "kestrel.evidence.v1":
                    errors.append(f"{bundle_id}: INVALID_SCHEMA")
                if doc.get("prev_hash") != meta["prev_hash"] or doc.get("prev_hash") != expected_prev:
                    errors.append(f"{bundle_id}: FILE_PREDECESSOR_MISMATCH")
                documents[bundle_id] = doc
            try:
                if tenant_dir.resolve() != tenant_dir:
                    errors.append("PATH_MISMATCH (tenant directory symlink)")
                else:
                    for path in sorted(tenant_dir.rglob("*.json")):
                        if path not in indexed_paths:
                            errors.append(f"{path.relative_to(tenant_dir)}: UNINDEXED_FILE")
            except (OSError, RuntimeError) as exc:
                errors.append(f"UNREADABLE_DIRECTORY ({type(exc).__name__})")
        return ({"tenant_code": tenant_code, "length": len(chain), "ok": not errors, "errors": errors}, documents)

    def verify_chain(self, tenant_code: str) -> dict[str, Any]:
        """Fail closed on missing, misplaced, unindexed or inconsistent evidence."""
        return self._inspect_chain(tenant_code)[0]

    def produce_full_basis(self, event_id: str, tenant_code: str) -> dict[str, Any]:
        """Board commitment 3: full basis on request — measure latency."""
        started = time.perf_counter()
        metas = self.db.evidence_for_event(event_id, tenant_code)
        if not metas:
            raise FileNotFoundError(f"no evidence for {event_id} under {tenant_code}")
        # Latest bundle
        meta = metas[-1]
        doc = self.get(meta["bundle_id"], tenant_code=tenant_code, measure=True)
        elapsed_ms = (time.perf_counter() - started) * 1000
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
