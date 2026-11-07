"""Executed validation helper; outputs stay under the supplied temp directory."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from kestrel.api.app import create_app
from kestrel.config import Settings
from kestrel.service import AdjudicationService


def main() -> None:
    """Replay each persisted result; verify chains; capture API/UI and outcome diffs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root

    def save(name, value):
        (root / name).write_text(json.dumps(value, indent=2, default=str) + "\n")

    def service(prefix):
        svc = AdjudicationService(Settings(db_path=root / f"{prefix}.sqlite", evidence_dir=root / f"{prefix}-evidence"))
        svc.bootstrap()
        return svc

    svc = service("verified")
    rows = list(csv.DictReader((root / "verified.csv").open()))
    replays = [svc.replay_from_bundle(r["bundle_id"], r["tenant_code"]) for r in rows]
    chains = {tenant: svc.verify_tenant_chain(tenant) for tenant in sorted({r["tenant_code"] for r in rows})}
    assert all(r["identical"] for r in replays)
    assert all(c["ok"] for c in chains.values())
    save(
        "replay-and-chains.json",
        {
            "replayed": len(replays),
            "identical": sum(r["identical"] for r in replays),
            "replay_rows": [
                {k: r[k] for k in ("bundle_id", "identical", "original_disposition", "replay_disposition")}
                for r in replays
            ],
            "chains": chains,
        },
    )
    before = service("before")
    before_rows = {r["event_id"]: r for r in csv.DictReader((root / "before.csv").open())}
    changes = []
    examples = []
    rule_counts = Counter()
    historic_groups = Counter()
    for r in rows:
        result = svc.engine.adjudicate(svc.pack.event_by_id(r["event_id"]))
        rule_counts[(result.recommendation, result.evidence["decision"]["rule"])] += 1
        historic_groups[(result.historical_classification, result.recommendation)] += 1
        old_row = before_rows[r["event_id"]]
        old_doc = before.evidence.get(old_row["bundle_id"], tenant_code=old_row["tenant_code"])
        new_doc = svc.evidence.get(r["bundle_id"], tenant_code=r["tenant_code"])
        old = old_doc["inputs"]["expected_result"]
        new = new_doc["inputs"]["expected_result"]
        if old["recommendation"] != new["recommendation"]:
            changes.append(
                {
                    "event_id": r["event_id"],
                    "before": old["recommendation"],
                    "after": new["recommendation"],
                    "historical_classification": result.historical_classification,
                    "rule": result.evidence["decision"]["rule"],
                    "reason": result.evidence["closure_assessment"]["limitation"],
                }
            )
        if r["event_id"] in {"EXC-112198", "EXC-112352", "EXC-107133"}:
            examples.append({"event_id": r["event_id"], "before": old, "after": new})
    save("changed-events.json", changes)
    save("before-after-examples.json", examples)
    save(
        "rule-inventory.json",
        [{"recommendation": d, "rule": rule, "count": n} for (d, rule), n in sorted(rule_counts.items())],
    )
    save(
        "historical-reference-groups.json",
        [
            {"classification": h, "recommendation": d, "count": n}
            for (h, d), n in sorted(historic_groups.items(), key=str)
        ],
    )
    old_86 = json.loads((Path(__file__).resolve().parents[1] / "storage-limits-review" / "86-after.json").read_text())
    current_86 = []
    for previous in old_86:
        result = svc.engine.adjudicate(svc.pack.event_by_id(previous["event_id"]))
        current_86.append(
            {
                "event_id": result.event_id,
                "raw_storage_text": result.evidence["labelled_range"]["text"],
                "parsed_limit": result.evidence["labelled_range"],
                "outcome": result.recommendation,
                "rule": result.evidence["decision"]["rule"],
            }
        )
    save("86-current.json", current_86)
    client = TestClient(create_app(service("surfaces")))
    candidate = client.post("/adjudicate", json={"event_id": "EXC-112198"})
    assert candidate.status_code == 200
    sample = candidate.json()
    save("sample-api.json", sample)
    save("openapi.json", client.get("/openapi.json").json())
    html = client.get("/ui").text
    summary = re.search(r'<section class="card" aria-label="Closure verification counts">.*?</section>', html).group()
    (root / "ui-render-summary.html").write_text(summary + "\n")
    doc = client.get(f"/evidence/{sample['bundle_id']}", params={"tenant_code": sample["tenant_code"]}).json()
    save(
        "sample-evidence-excerpt.json",
        {
            "excerpt_only": True,
            "bundle_id": doc["bundle_id"],
            "content_hash": doc["content_hash"],
            "recommendation": doc["recommendation"],
            "alert": doc["inputs"]["alert"],
            "decision": doc["inputs"]["resolution"]["decision"],
            "closure_assessment": doc["inputs"]["resolution"]["closure_assessment"],
        },
    )
    print(
        json.dumps(
            {
                "replayed": len(replays),
                "identical": sum(r["identical"] for r in replays),
                "chains_ok": sum(c["ok"] for c in chains.values()),
                "chain_bundles": sum(c["length"] for c in chains.values()),
                "changed_events": len(changes),
                "candidate_api_status": candidate.status_code,
                "candidate_case_state": sample["case_state"],
                "ui_summary": summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
