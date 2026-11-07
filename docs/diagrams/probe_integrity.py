"""Isolated integrity probe; never alter the primary run or engine code."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from kestrel.storage.bitemporal import BitemporalStore
from kestrel.storage.evidence import EvidenceStore, canonical_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.bundle.read_text())
    with tempfile.TemporaryDirectory(prefix="kestrel-doc-integrity-probe-") as temporary:
        root = Path(temporary)
        store = BitemporalStore(root / "probe.sqlite")
        evidence = EvidenceStore(root / "evidence", store)
        keys = (
            "tenant_code",
            "event_id",
            "recommendation",
            "inputs",
            "reasoning_steps",
            "rule_pack_version",
            "ref_snapshot_id",
            "code_version",
        )
        doc = evidence.write_bundle(**{key: original[key] for key in keys})
        before = evidence.verify_chain(doc["tenant_code"])
        old_hash = doc["content_hash"]
        doc["reasoning_steps"].append("ISOLATED INTEGRITY PROBE: not original case reasoning")
        core = {k: v for k, v in doc.items() if k not in {"bundle_id", "content_hash", "prev_hash", "schema"}}
        doc["content_hash"] = canonical_hash(core)
        meta = store.get_evidence_meta(doc["bundle_id"], tenant_code=doc["tenant_code"])
        Path(meta["path"]).write_text(json.dumps(doc))
        after = evidence.verify_chain(doc["tenant_code"])
        result = {
            "scope": "temporary single-bundle copy; primary run/data/code untouched",
            "before": before,
            "after_resealed_reasoning_edit": after,
            "content_hash_changed": old_hash != doc["content_hash"],
            "indexed_hash_unchanged": meta["content_hash"] == old_hash,
            "file_hash_differs_from_index": meta["content_hash"] != doc["content_hash"],
            "signing_bypass_tested": False,
            "clinical_outcome_changed": False,
        }
        assert before["ok"] and result["file_hash_differs_from_index"] and not after["ok"]
        assert any("INDEX_HASH_MISMATCH" in error for error in after["errors"])
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
