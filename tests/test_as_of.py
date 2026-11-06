"""As-of lookups: what was in force on a given date."""

from __future__ import annotations

from datetime import date

from kestrel.rules.as_of import parse_storage_range, sop_in_force
from tests._base import _KestrelTestCase


class TestBitemporalAsOf(_KestrelTestCase):
    """Bitemporal SOP as-at lookups (Aura AUD-2603 date, Kaveri overlap)."""

    def test_aura_sop_as_of_audit_date(self) -> None:
        """SOP in force for T-AURA on 2025-08-14 must be answerable."""
        hit = self.svc.store.sop_in_force("T-AURA", "Temperature Excursion Management", date(2025, 8, 14))
        self.assertIsNotNone(hit["record"])
        self.assertTrue(hit["record"]["payload"]["doc_id"])
        vf = hit["record"]["valid_from"][:10]
        self.assertLessEqual(vf, "2025-08-14")

    def test_kaveri_sop_overlap(self) -> None:
        """T-KAVERI Temperature Excursion Management overlaps on 2026-07-28."""
        hit = self.svc.store.sop_in_force("T-KAVERI", "Temperature Excursion Management", date(2026, 7, 28))
        self.assertIsNotNone(hit["record"])
        self.assertTrue(hit["overlap_conflict"])


class TestAsOfPack(_KestrelTestCase):
    """In-memory pack as-of SOP helpers and storage-range parsing."""

    def test_kaveri_sop_overlap_on_excursion_date(self) -> None:
        """Pack-level sop_in_force reports overlap and selects highest revision."""
        hit = sop_in_force(
            self.svc.pack.sops,  # type: ignore[union-attr]
            "T-KAVERI",
            "Temperature Excursion Management",
            date(2026, 7, 28),
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.overlap_conflict)
        self.assertGreaterEqual(len(hit.competing), 2)
        self.assertTrue("03" in str(hit.record.get("revision")) or "3" in str(hit.record.get("revision")))

    def test_parse_2_8_variants(self) -> None:
        """parse_storage_range accepts common 2–8 °C and CRT spellings."""
        self.assertEqual(parse_storage_range("2-8 °C"), (2.0, 8.0))
        self.assertEqual(parse_storage_range("+2/+8 C"), (2.0, 8.0))
        self.assertEqual(parse_storage_range("Store at 2–8°C. Do not freeze."), (2.0, 8.0))
        low, high = parse_storage_range("CRT 15-25C")
        self.assertEqual(low, 15.0)
        self.assertEqual(high, 25.0)

    def test_aura_sop_single_rev_on_date(self) -> None:
        """Aura SOP lookup on AUD-2603 date returns a concrete doc_id."""
        hit = sop_in_force(
            self.svc.pack.sops,  # type: ignore[union-attr]
            "T-AURA",
            "Temperature Excursion Management",
            date(2025, 8, 14),
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.record.get("doc_id"))
