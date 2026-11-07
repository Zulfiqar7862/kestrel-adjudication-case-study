"""Capture a real existing run for documentation; never sign, send or alter data/."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from kestrel.config import Settings
from kestrel.service import AdjudicationService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--case-output", type=Path, default=Path("docs/images/workflow-run.json"))
    args = parser.parse_args()
    root = args.run_dir
    service = AdjudicationService(
        Settings(db_path=root / "run.sqlite", evidence_dir=root / "evidence", log_level="WARNING")
    )
    service.bootstrap()
    rows = list(csv.DictReader((root / "results.csv").open()))
    saved = next(r for r in rows if r["event_id"] == "EXC-107133")
    event = service.pack.event_by_id("EXC-107133")
    result = service.engine.adjudicate(event)
    bundle = service.evidence.get(saved["bundle_id"], tenant_code=saved["tenant_code"])
    notification = next(
        o for o in service.notifications.queue(saved["tenant_code"]) if o["event_id"] == saved["event_id"]
    )
    replays = [service.replay_from_bundle(r["bundle_id"], r["tenant_code"]) for r in rows]
    chains = {tenant: service.verify_tenant_chain(tenant) for tenant in sorted({r["tenant_code"] for r in rows})}
    before = {
        r["event_id"]: r
        for r in csv.DictReader(Path("docs/validation/notification-obligations-review/verified.csv").open())
    }
    changed = [r["event_id"] for r in rows if r["recommendation"] != before[r["event_id"]]["recommendation"]]
    summary = {
        "events": len(rows),
        "counts": json.loads((root / "run-all.json").read_text())["counts"],
        "notification_counts": service.notifications.counts(),
        "replays": len(replays),
        "identical_replays": sum(r["identical"] for r in replays),
        "chains": chains,
        "recommendation_changes_from_62c498f": changed,
    }
    assert len(rows) == 420 and summary["identical_replays"] == 420
    assert all(c["ok"] for c in chains.values())
    record = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path("data").iterdir() if p.is_file()
        },
        "event": event,
        "result": asdict(result),
        "case": service.store.get_case(saved["case_id"]),
        "bundle": {
            k: bundle[k] for k in ("bundle_id", "content_hash", "prev_hash", "rule_pack_version", "code_version")
        },
        "notification": notification,
        "replay": next(r for r in replays if r["bundle_id"] == saved["bundle_id"]),
        "summary": summary,
    }
    args.case_output.write_text(json.dumps(record, indent=2, default=str) + "\n")
    (root / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
