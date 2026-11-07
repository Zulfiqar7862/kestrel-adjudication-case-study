"""Closure metrics distinguish recommendation labels from independent verification."""

from typing import Any, Iterable

from kestrel.domain import Disposition


def closure_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Count actual assessments; never infer verification from AUTO_CLOSE alone."""
    counts = {"verified_auto_close": 0, "historical_candidates_unverified": 0, "other_auto_close_unverified": 0}
    for row in rows:
        if row["recommendation"] == Disposition.HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED:
            counts["historical_candidates_unverified"] += 1
        elif row["recommendation"] == Disposition.AUTO_CLOSE:
            # Reserved for a future validated verification adapter; current input
            # has no independent closure artifacts and emits no verified status.
            key = (
                "verified_auto_close" if row.get("closure_eligibility") == "verified" else "other_auto_close_unverified"
            )
            counts[key] += 1
    return counts
