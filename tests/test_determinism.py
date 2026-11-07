"""Same input, same output: full-pack determinism."""

from __future__ import annotations

import hashlib
import json

from tests._base import _KestrelTestCase


class TestDeterminism(_KestrelTestCase):
    """Engine determinism: identical inputs yield byte-identical decision hashes."""

    def test_run_twice_byte_identical_decision_hashes(self) -> None:
        """Adjudicate the full pack twice; SHA-256 of decision rows must match."""
        assert self.svc.engine and self.svc.pack

        def _digest() -> str:
            rows = []
            for event in self.svc.pack.events:  # type: ignore[union-attr]
                r = self.svc.engine.adjudicate(event)  # type: ignore[union-attr]
                rows.append(
                    {
                        "event_id": r.event_id,
                        "recommendation": r.recommendation,
                        "confidence": r.confidence,
                        "triage_label": r.triage_label,
                        "reported_max_temp_c": r.reported_max_temp_c,
                        "bulletin_applied": r.bulletin_applied,
                        "rationale": list(r.rationale),
                    }
                )
            blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
            return hashlib.sha256(blob.encode("utf-8")).hexdigest()

        h1 = _digest()
        h2 = _digest()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)
