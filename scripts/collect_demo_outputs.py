#!/usr/bin/env python3
"""Collect demo artefacts into examples/ after a local run."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
EX.mkdir(exist_ok=True)

# Copy latency note from basis if present
basis = EX / "basis_EXC-107133.json"
if basis.exists():
    data = json.loads(basis.read_text())
    (EX / "retrieval_latency.txt").write_text(
        f"event_id=EXC-107133\n"
        f"retrieval_latency_ms={data.get('retrieval_latency_ms')}\n"
        f"within_one_hour={data.get('within_one_hour')}\n"
        f"retention_until={data.get('retention_until')}\n"
        f"bundle_id={data.get('bundle', {}).get('bundle_id')}\n",
        encoding="utf-8",
    )
    # slim evidence sample
    bundle = data.get("bundle") or {}
    (EX / "evidence_bundle_EXC-107133.json").write_text(
        json.dumps(bundle, indent=2, default=str), encoding="utf-8"
    )
print("demo outputs ready in examples/")
