"""kestrel CLI — ingest, adjudicate, evidence, replay, shadow, queue."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from kestrel_sentinel.config import get_settings
from kestrel_sentinel.logging_setup import setup_logging
from kestrel_sentinel.service import AdjudicationService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kestrel", description="Kestrel Sentinel adjudication platform")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--pack", type=Path, default=None)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--log-level", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("ingest", help="Load workbook into bitemporal store")
    p_boot.add_argument("--reload", action="store_true")

    p_adj = sub.add_parser("adjudicate", help="Adjudicate one or all events")
    p_adj.add_argument("--event", type=str, default=None)
    p_adj.add_argument("--limit", type=int, default=None)
    p_adj.add_argument("--no-persist", action="store_true")
    p_adj.add_argument("--out", type=Path, default=Path("examples/adjudication_results.csv"))

    p_basis = sub.add_parser("basis", help="Produce full evidence basis for an event")
    p_basis.add_argument("--event", required=True)
    p_basis.add_argument("--tenant", required=True)
    p_basis.add_argument("--out", type=Path, default=None)

    p_verify = sub.add_parser("verify-chain", help="Verify tenant evidence hash chain")
    p_verify.add_argument("--tenant", required=True)

    p_replay = sub.add_parser("replay", help="Replay decision from evidence bundle")
    p_replay.add_argument("--bundle", required=True)
    p_replay.add_argument("--tenant", required=True)

    p_shadow = sub.add_parser("shadow-bulletin", help="Dr Rao gate: TT-CB-114 shadow diff")
    p_shadow.add_argument("--out", type=Path, default=Path("examples/shadow_bulletin_diff.json"))

    p_queue = sub.add_parser("queue", help="Show storm-safe priority queue")
    p_queue.add_argument("--tenant", default=None)
    p_queue.add_argument("--limit", type=int, default=20)

    p_asof = sub.add_parser("as-of-sop", help="SOP in force as-at a date")
    p_asof.add_argument("--tenant", required=True)
    p_asof.add_argument("--date", required=True, help="YYYY-MM-DD")

    p_api = sub.add_parser("serve", help="Run HTTP API")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    settings = get_settings()
    if args.db:
        settings.db_path = args.db
    if args.pack:
        settings.data_pack = args.pack
    if args.evidence_dir:
        settings.evidence_dir = args.evidence_dir
    setup_logging(args.log_level or settings.log_level)

    svc = AdjudicationService(settings)

    if args.cmd == "ingest":
        snap = svc.bootstrap(reload=args.reload)
        print(json.dumps({"snapshot_id": snap, "alerts": svc.store.get_meta("loaded_alerts")}, indent=2))
        return 0

    if args.cmd == "serve":
        import uvicorn
        from kestrel_sentinel.api.app import create_app

        svc.bootstrap()
        app = create_app(svc)
        uvicorn.run(app, host=args.host or settings.api_host, port=args.port or settings.api_port)
        return 0

    # commands needing bootstrap
    svc.bootstrap()

    if args.cmd == "adjudicate":
        if args.event:
            out = svc.adjudicate_event(args.event, persist=not args.no_persist)
            r = out["result"]
            payload = {
                "event_id": r.event_id,
                "recommendation": r.recommendation,
                "confidence": r.confidence,
                "bundle_id": (out["bundle"] or {}).get("bundle_id"),
                "case_id": (out["case"] or {}).get("case_id"),
                "rationale": r.rationale,
            }
            print(json.dumps(payload, indent=2, default=str))
            if out.get("bundle") and args.out:
                # also write showcase
                examples = Path("examples")
                examples.mkdir(exist_ok=True)
                (examples / f"evidence_{args.event}.json").write_text(
                    json.dumps(out["bundle"], indent=2, default=str), encoding="utf-8"
                )
            return 0
        summary = svc.adjudicate_all(limit=args.limit, persist=not args.no_persist)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "event_id",
                    "tenant_code",
                    "recommendation",
                    "bundle_id",
                    "case_id",
                    "reg_deadline_utc",
                ],
            )
            w.writeheader()
            for row in summary["rows"]:
                w.writerow(row)
        print(json.dumps({"count": summary["count"], "out": str(args.out), "snapshot_id": summary["snapshot_id"]}, indent=2))
        return 0

    if args.cmd == "basis":
        basis = svc.full_basis(args.event, args.tenant)
        out = args.out or Path(f"examples/basis_{args.event}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(basis, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "event_id": args.event,
                    "bundle_id": basis["bundle"]["bundle_id"],
                    "retrieval_latency_ms": basis["retrieval_latency_ms"],
                    "within_one_hour": basis["within_one_hour"],
                    "retention_until": basis["retention_until"],
                    "wrote": str(out),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "verify-chain":
        print(json.dumps(svc.verify_tenant_chain(args.tenant), indent=2))
        return 0

    if args.cmd == "replay":
        print(json.dumps(svc.replay_from_bundle(args.bundle, args.tenant), indent=2, default=str))
        return 0

    if args.cmd == "shadow-bulletin":
        report = svc.shadow_bulletin()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # keep file smaller in repo: truncate diff_rows in summary print but write full
        args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "change": report["change"],
                    "candidates": report["candidates"],
                    "diffs": report["diffs"],
                    "wrote": str(args.out),
                    "rao_gate": report["rao_gate"],
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "queue":
        q = svc.lifecycle.storm_safe_queue(tenant_code=args.tenant, limit=args.limit)
        print(json.dumps(q, indent=2, default=str))
        return 0

    if args.cmd == "as-of-sop":
        hit = svc.as_of_sop(args.tenant, args.date)
        rec = hit.get("record")
        print(
            json.dumps(
                {
                    "tenant": args.tenant,
                    "as_of": args.date,
                    "overlap_conflict": hit.get("overlap_conflict"),
                    "selected": None
                    if not rec
                    else {
                        "doc_id": rec["payload"].get("doc_id"),
                        "revision": rec["payload"].get("revision"),
                        "valid_from": rec.get("valid_from"),
                        "valid_to": rec.get("valid_to"),
                    },
                    "competing_revisions": [
                        c["payload"].get("revision") for c in hit.get("competing") or []
                    ],
                },
                indent=2,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
