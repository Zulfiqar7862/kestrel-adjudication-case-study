"""Command-line entry point (`kestrel ...`)."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Optional

from kestrel.api.app import serve_http
from kestrel.config import get_settings
from kestrel.logging_setup import setup_logging
from kestrel.service import AdjudicationService


def _default_work_dir() -> Path:
    """Return the temp working directory for DB/evidence/CSV outputs (created if needed)."""
    work_dir = Path(tempfile.gettempdir()) / "kestrel-adjudication"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _run_tests() -> int:
    """Run the unittest suite under tests/ and return a process exit code."""
    import unittest

    repo_root = Path(__file__).resolve().parents[2]
    suite = unittest.TestLoader().discover(str(repo_root / "tests"), top_level_dir=str(repo_root))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _svc_from_args(args: argparse.Namespace) -> AdjudicationService:
    """Build the service from settings (KESTREL_* env vars), then apply any CLI flag overrides."""
    settings = get_settings()
    if args.db:
        settings.db_path = Path(args.db)
    if args.pack:
        settings.data_pack = Path(args.pack)
    if args.evidence_dir:
        settings.evidence_dir = Path(args.evidence_dir)
    if args.log_level:
        settings.log_level = args.log_level
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    setup_logging(settings.log_level)
    return AdjudicationService(settings)


RESULT_CSV_FIELDS = [
    "event_id",
    "tenant_code",
    "recommendation",
    "bundle_id",
    "case_id",
    "reg_deadline_utc",
    "historical_classification",
    "closure_eligibility",
    "independent_closure_evidence",
    "requires_human_review",
]
SHOWCASE_EVENT_ID = "EXC-107133"


def build_parser() -> argparse.ArgumentParser:
    """Define every sub-command and its flags."""
    parser = argparse.ArgumentParser(
        prog="kestrel",
        description="Kestrel Sentinel — as-of adjudication & evidence platform",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: temp dir)")
    parser.add_argument("--pack", type=Path, default=None, help="Workbook path")
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING (default: INFO)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("ingest", help="Load workbook into bitemporal store")
    p_boot.add_argument("--reload", action="store_true")

    p_adj = sub.add_parser("adjudicate", help="Adjudicate one event or a limited batch")
    p_adj.add_argument("--event", type=str, default=None)
    p_adj.add_argument("--limit", type=int, default=None)
    p_adj.add_argument("--no-persist", action="store_true")
    p_adj.add_argument("--out", type=Path, default=None)

    p_all = sub.add_parser("run-all", help="Adjudicate all 420 events; print disposition counts")
    p_all.add_argument("--no-persist", action="store_true")
    p_all.add_argument("--out", type=Path, default=None)

    p_basis = sub.add_parser("basis", help="Full evidence basis for an event")
    p_basis.add_argument("--event", required=True)
    p_basis.add_argument("--tenant", required=True)
    p_basis.add_argument("--out", type=Path, default=None)

    p_verify = sub.add_parser("verify", help="Verify tenant evidence hash chain")
    p_verify.add_argument("--tenant", required=True)

    p_replay = sub.add_parser("replay", help="Replay decision from evidence bundle")
    p_replay.add_argument("--bundle", required=True)
    p_replay.add_argument("--tenant", required=True)

    p_shadow = sub.add_parser("shadow-bulletin", help="Dr Rao gate: TT-CB-114 shadow diff")
    p_shadow.add_argument("--out", type=Path, default=None)

    p_not = sub.add_parser("notifications", help="Independent filing queue; no evidence assembly")
    p_not.add_argument("--tenant", required=True)

    p_queue = sub.add_parser("queue", help="Storm-safe priority queue")
    p_queue.add_argument("--tenant", default=None)
    p_queue.add_argument("--limit", type=int, default=20)

    p_asof = sub.add_parser("as-of-sop", help="SOP in force as-at a date")
    p_asof.add_argument("--tenant", required=True)
    p_asof.add_argument("--date", required=True, help="YYYY-MM-DD")

    p_api = sub.add_parser("serve", help="Run FastAPI+uvicorn HTTP API (lazy deps)")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)

    sub.add_parser("health", help="3am ops signals: deadlines, chain, mix drift, feed age")
    sub.add_parser("monitor", help="Alias for health")
    sub.add_parser("agreement", help="Stratify engine vs historical final/assistant agreement")

    sub.add_parser("test", help="Run the test suite in tests/ (same as `pytest`)")
    sub.add_parser("selftest", help="Alias for test")
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _output_path(requested: Optional[Path], default_name: str) -> Path:
    path = requested or (_default_work_dir() / default_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_results_csv(rows: list[dict], out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _cmd_ingest(svc: AdjudicationService, args: argparse.Namespace) -> int:
    snapshot_id = svc.bootstrap(reload=args.reload)
    _print_json({"snapshot_id": snapshot_id, "alerts": svc.store.get_meta("loaded_alerts")})
    return 0


def _cmd_serve(svc: AdjudicationService, args: argparse.Namespace) -> int:
    serve_http(svc, host=args.host or svc.settings.api_host, port=args.port or svc.settings.api_port)
    return 0


def _cmd_adjudicate_one(svc: AdjudicationService, args: argparse.Namespace) -> int:
    out = svc.adjudicate_event(args.event, persist=not args.no_persist)
    result = out["result"]
    _print_json(
        {
            "event_id": result.event_id,
            "recommendation": result.recommendation,
            **result.closure_fields(),
            "requires_human_signature": result.requires_human_signature,
            "confidence": result.confidence,
            "bundle_id": (out["bundle"] or {}).get("bundle_id"),
            "case_id": (out["case"] or {}).get("case_id"),
            "rationale": result.rationale,
        }
    )
    return 0


def _cmd_adjudicate(svc: AdjudicationService, args: argparse.Namespace) -> int:
    if args.event:
        return _cmd_adjudicate_one(svc, args)
    summary = svc.adjudicate_all(limit=args.limit, persist=not args.no_persist)
    out_path = _output_path(args.out, "adjudication_results.csv")
    _write_results_csv(summary["rows"], out_path)
    counts = Counter(row["recommendation"] for row in summary["rows"])
    _print_json(
        {
            "count": summary["count"],
            "out": str(out_path),
            "snapshot_id": summary["snapshot_id"],
            "counts": dict(counts),
            "closure_counts": summary["closure_counts"],
        }
    )
    return 0


def _cmd_run_all(svc: AdjudicationService, args: argparse.Namespace) -> int:
    summary = svc.adjudicate_all(persist=not args.no_persist)
    out_path = _output_path(args.out, "adjudication_results.csv")
    _write_results_csv(summary["rows"], out_path)
    counts = Counter(row["recommendation"] for row in summary["rows"])
    showcase = next((row for row in summary["rows"] if row["event_id"] == SHOWCASE_EVENT_ID), None)
    _print_json(
        {
            "count": summary["count"],
            "counts": dict(sorted(counts.items())),
            "closure_counts": summary["closure_counts"],
            SHOWCASE_EVENT_ID: showcase,
            "out": str(out_path),
            "snapshot_id": summary["snapshot_id"],
        }
    )
    return 0


def _cmd_basis(svc: AdjudicationService, args: argparse.Namespace) -> int:
    basis = svc.full_basis(args.event, args.tenant)
    out_path = _output_path(args.out, f"basis_{args.event}.json")
    out_path.write_text(json.dumps(basis, indent=2, default=str), encoding="utf-8")
    _print_json(
        {
            "event_id": args.event,
            "bundle_id": basis["bundle"]["bundle_id"],
            "retrieval_latency_ms": basis["retrieval_latency_ms"],
            "within_one_hour": basis["within_one_hour"],
            "retention_until": basis["retention_until"],
            "wrote": str(out_path),
        }
    )
    return 0


def _cmd_verify(svc: AdjudicationService, args: argparse.Namespace) -> int:
    report = svc.verify_tenant_chain(args.tenant)
    _print_json(report)
    return 0 if report["ok"] else 1


def _cmd_replay(svc: AdjudicationService, args: argparse.Namespace) -> int:
    _print_json(svc.replay_from_bundle(args.bundle, args.tenant))
    return 0


def _cmd_shadow_bulletin(svc: AdjudicationService, args: argparse.Namespace) -> int:
    report = svc.shadow_bulletin()
    out_path = _output_path(args.out, "shadow_bulletin_diff.json")
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    _print_json(
        {
            "change": report["change"],
            "candidates": report["candidates"],
            "diffs": report["diffs"],
            "disposition_flips": report["disposition_flips"],
            "wrote": str(out_path),
            "rao_gate": report["rao_gate"],
        }
    )
    return 0


def _cmd_notifications(svc: AdjudicationService, args: argparse.Namespace) -> int:
    _print_json({"items": svc.notifications.queue(args.tenant)})
    return 0


def _cmd_queue(svc: AdjudicationService, args: argparse.Namespace) -> int:
    _print_json(svc.lifecycle.storm_safe_queue(tenant_code=args.tenant, limit=args.limit))
    return 0


def _cmd_as_of_sop(svc: AdjudicationService, args: argparse.Namespace) -> int:
    hit = svc.as_of_sop(args.tenant, args.date)
    record = hit.get("record")
    selected = None
    if record:
        selected = {
            "doc_id": record["payload"].get("doc_id"),
            "revision": record["payload"].get("revision"),
            "valid_from": record.get("valid_from"),
            "valid_to": record.get("valid_to"),
        }
    _print_json(
        {
            "tenant": args.tenant,
            "as_of": args.date,
            "overlap_conflict": hit.get("overlap_conflict"),
            "selected": selected,
            "competing_revisions": [competitor["payload"].get("revision") for competitor in hit.get("competing") or []],
        }
    )
    return 0


def _cmd_health(svc: AdjudicationService, args: argparse.Namespace) -> int:
    _print_json(svc.health_report())
    return 0


AGREEMENT_HEADLINE_KEYS = (
    "events_total",
    "closure_counts",
    "events_with_historical_final",
    "agree_with_historical_final",
    "agree_with_historical_final_pct",
    "agree_with_assistant",
    "agree_with_assistant_pct",
)


def _cmd_agreement(svc: AdjudicationService, args: argparse.Namespace) -> int:
    report = svc.agreement_report()
    headline = {key: report[key] for key in AGREEMENT_HEADLINE_KEYS}
    headline.update(
        {
            "disagree_by_reason_top": list(report["disagree_by_reason"].items())[:8],
            "disagree_by_tenant": report["disagree_by_tenant"],
            "disagree_by_firmware": report["disagree_by_firmware"],
            "notes": report["notes"],
            "full_keys": sorted(report.keys()),
        }
    )
    _print_json({"headline": headline, "report": report})
    return 0


# Commands that run before (or instead of) the default bootstrap.
_PRE_BOOTSTRAP = {"ingest": _cmd_ingest, "serve": _cmd_serve, "notifications": _cmd_notifications}

# Commands that need the workbook loaded first.
_COMMANDS = {
    "adjudicate": _cmd_adjudicate,
    "run-all": _cmd_run_all,
    "basis": _cmd_basis,
    "verify": _cmd_verify,
    "replay": _cmd_replay,
    "shadow-bulletin": _cmd_shadow_bulletin,
    "queue": _cmd_queue,
    "as-of-sop": _cmd_as_of_sop,
    "health": _cmd_health,
    "monitor": _cmd_health,
    "agreement": _cmd_agreement,
}


def main(argv: Optional[list[str]] = None) -> int:
    """Parse arguments and run the chosen sub-command; returns a process exit code."""
    args = build_parser().parse_args(argv)
    if args.cmd in {"test", "selftest"}:
        return _run_tests()
    svc = _svc_from_args(args)
    if args.cmd in _PRE_BOOTSTRAP:
        return _PRE_BOOTSTRAP[args.cmd](svc, args)
    svc.bootstrap()
    handler = _COMMANDS.get(args.cmd)
    return handler(svc, args) if handler else 1
