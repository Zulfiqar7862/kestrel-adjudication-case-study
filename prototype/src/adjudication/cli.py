"""Run the adjudication engine against the reference data pack."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from .engine import AdjudicationEngine
from .pack import DataPack

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACK = ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "output"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kestrel as-of adjudication prototype")
    p.add_argument("--pack", type=Path, default=DEFAULT_PACK, help="Path to data pack xlsx")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    p.add_argument("--event", type=str, default=None, help="Single event_id to adjudicate")
    p.add_argument("--limit", type=int, default=None, help="Process only first N events")
    args = p.parse_args(argv)

    if not args.pack.exists():
        print(f"Pack not found: {args.pack}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    pack = DataPack.load(args.pack)
    engine = AdjudicationEngine(pack)

    events = pack.events
    if args.event:
        ev = pack.event_by_id(args.event)
        if not ev:
            print(f"Unknown event_id: {args.event}", file=sys.stderr)
            return 2
        events = [ev]
    if args.limit:
        events = events[: args.limit]

    results = [engine.adjudicate(e) for e in events]

    # CSV
    csv_path = args.out / "results.csv"
    fieldnames = [
        "event_id",
        "tenant_code",
        "recommendation",
        "requires_human_signature",
        "confidence",
        "triage_label",
        "product_match_method",
        "product_sku",
        "product_brand",
        "stability_study_ref",
        "sop_doc_id",
        "sop_revision",
        "sop_overlap_conflict",
        "carrier_contract_id",
        "carrier_has_cold_chain_clause",
        "corrected_max_temp_c",
        "bulletin_applied",
        "regulator_reportable",
        "reg_window_hours",
        "reg_deadline_utc",
        "historical_recommendation",
        "historical_final_disposition",
        "agrees_with_historical_final",
        "agrees_with_historical_engine",
        "rationale",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = r.to_row()
            w.writerow({k: row.get(k) for k in fieldnames})

    # JSON evidence for a few showcase cases
    showcase_ids = ["EXC-107133", "EXC-110497", "EXC-110490", "EXC-110448", "EXC-110483"]
    showcase = {r.event_id: r.evidence | {"recommendation": r.recommendation, "rationale": r.rationale} for r in results if r.event_id in showcase_ids}
    (args.out / "showcase_evidence.json").write_text(json.dumps(showcase, indent=2, default=str), encoding="utf-8")

    # Summary
    rec_counts = Counter(r.recommendation for r in results)
    with_final = [r for r in results if r.historical_final_disposition]
    agree_final = [r for r in with_final if r.agrees_with_historical_final]
    with_eng = [r for r in results if r.historical_recommendation]
    agree_eng = [r for r in with_eng if r.agrees_with_historical_engine]
    auto = sum(1 for r in results if r.recommendation == "AUTO_CLOSE")
    human = sum(1 for r in results if r.requires_human_signature)
    bulletin = sum(1 for r in results if r.bulletin_applied)
    sop_conflict = sum(1 for r in results if r.sop_overlap_conflict)

    # Golden: EXC-107133 must be RELEASE_WITH_NOTE (brief narrative)
    g107 = next((r for r in results if r.event_id == "EXC-107133"), None)

    lines = [
        "Kestrel as-of adjudication — run summary",
        f"pack: {args.pack}",
        f"events_processed: {len(results)}",
        f"recommendations: {dict(rec_counts)}",
        f"auto_close: {auto} ({100*auto/max(len(results),1):.1f}%)",
        f"requires_human_signature: {human}",
        f"bulletin_tt_cb_114_applied: {bulletin}",
        f"sop_overlap_conflicts: {sop_conflict}",
        f"agree_with_historical_final: {len(agree_final)}/{len(with_final)} "
        f"({100*len(agree_final)/max(len(with_final),1):.1f}%)",
        f"agree_with_historical_engine_col: {len(agree_eng)}/{len(with_eng)} "
        f"({100*len(agree_eng)/max(len(with_eng),1):.1f}%)",
        f"EXC-107133: {g107.recommendation if g107 else 'NOT_IN_RUN'} "
        f"(expected RELEASE_WITH_NOTE; confidence={getattr(g107,'confidence',None)})",
        f"wrote: {csv_path}",
        f"wrote: {args.out / 'showcase_evidence.json'}",
        "",
        "Note: historical 'rules_engine_recommendation' column is the 2024+ LLM",
        "recommendation assistant draft (pack README), not a pure rules output.",
        "Agreement rates are diagnostic, not a pass/fail gate — Dr Rao wants",
        "diffs explained, not maximised away.",
    ]
    summary = "\n".join(lines) + "\n"
    (args.out / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
