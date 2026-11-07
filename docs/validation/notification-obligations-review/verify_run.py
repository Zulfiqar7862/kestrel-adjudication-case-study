"""Verify the actual persisted sample, not a historical accuracy claim."""

import argparse
import csv
import json
from pathlib import Path

from kestrel.config import Settings
from kestrel.service import AdjudicationService

parser = argparse.ArgumentParser()
parser.add_argument("--db", type=Path, required=True)
parser.add_argument("--evidence-dir", type=Path, required=True)
parser.add_argument("--csv", type=Path, required=True)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
svc = AdjudicationService(Settings(db_path=args.db, evidence_dir=args.evidence_dir, log_level="WARNING"))
rows = list(csv.DictReader(args.csv.open()))
before = {row["event_id"]: row for row in csv.DictReader(args.baseline.open())}
replays = [svc.replay_from_bundle(row["bundle_id"], row["tenant_code"]) for row in rows]
tenants = sorted({row["tenant_code"] for row in rows})
chains = {tenant: svc.verify_tenant_chain(tenant) for tenant in tenants}
changed = [row["event_id"] for row in rows if row["recommendation"] != before[row["event_id"]]["recommendation"]]
clock_changed = [
    row["event_id"] for row in rows if row["reg_deadline_utc"] != before[row["event_id"]]["reg_deadline_utc"]
]
result = {
    "replays": len(replays),
    "identical": sum(r["identical"] for r in replays),
    "chains": chains,
    "outcome_changes": changed,
    "deadline_changes": clock_changed,
    "notification_counts": svc.notifications.counts(),
    "notification_count": sum(len(svc.notifications.queue(t)) for t in tenants),
}
assert len(rows) == 420 and result["identical"] == 420
assert all(c["ok"] for c in chains.values())
assert not changed
args.out.write_text(json.dumps(result, indent=2, default=str) + "\n")
print(json.dumps(result, indent=2, default=str))
