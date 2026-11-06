"""Shadow replay: re-adjudicate past cases under a bulletin or rule change and diff."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from kestrel.engine import BULLETIN_BIAS_C, BULLETIN_FW, AdjudicationEngine
from kestrel.ingest import DataPack

"""Dr Rao gate: re-adjudicate past cases under a reference/rules change and diff."""


def shadow_replay_bulletin(
    pack: DataPack,
    engine: AdjudicationEngine,
    *,
    firmware: str = BULLETIN_FW,
    bias_c: float = BULLETIN_BIAS_C,
    event_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Simulate April TT-CB-114 style change: ensure bulletin bias applied and diff outcomes.

    Baseline = engine as configured today (already applies bulletin).
    Alternate = force-disable bulletin correction to show what would have differed
    without the calibration notice — or re-run with bias forced on all matching FW.
    """
    events = pack.events
    if event_ids:
        idset = set(event_ids)
        events = [event for event in events if event.get("event_id") in idset]
    else:
        events = [event for event in events if str(event.get("logger_fw")) == firmware]

    diffs = []
    for event in events:
        baseline = engine.adjudicate(event)
        # Alternate: strip firmware so bulletin path does not fire
        alt_event = deepcopy(event)
        alt_event["logger_fw"] = "TT-DISABLED"
        alternate = engine.adjudicate(alt_event)
        if baseline.recommendation != alternate.recommendation or (
            baseline.corrected_max_temp_c != alternate.corrected_max_temp_c
        ):
            diffs.append(
                {
                    "event_id": event.get("event_id"),
                    "tenant_code": event.get("tenant_code"),
                    "firmware": event.get("logger_fw"),
                    "max_temp_c": event.get("max_temp_c"),
                    "with_bulletin": {
                        "recommendation": baseline.recommendation,
                        "corrected_max_temp_c": baseline.corrected_max_temp_c,
                    },
                    "without_bulletin": {
                        "recommendation": alternate.recommendation,
                        "corrected_max_temp_c": alternate.corrected_max_temp_c,
                    },
                    "historical_final": event.get("final_disposition"),
                }
            )
    return {
        "change": f"calibration bulletin {firmware} bias +{bias_c}°C (TT-CB-114 / INC-2506)",
        "candidates": len(events),
        "diffs": len(diffs),
        "diff_rows": diffs,
        "rao_gate": "Review diffs before promoting rule/reference change",
    }
