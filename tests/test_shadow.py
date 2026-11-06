"""Shadow replay of the TT-CB-114 firmware bulletin."""

from __future__ import annotations

from tests._base import _KestrelTestCase


class TestShadow(_KestrelTestCase):
    """Dr Rao TT-CB-114 shadow bulletin replay."""

    def test_shadow_bulletin_produces_diffs(self) -> None:
        """Shadow replay finds TT-2.14.3 candidates and emits diff rows."""
        report = self.svc.shadow_bulletin()
        self.assertGreater(report["candidates"], 0)
        self.assertTrue("TT-CB-114" in report["change"] or "bulletin" in report["change"].lower())
        self.assertIsInstance(report["diff_rows"], list)
