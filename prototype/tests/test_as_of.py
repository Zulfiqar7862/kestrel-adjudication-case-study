from datetime import date

from adjudication.as_of import sop_in_force, parse_storage_range


def test_kaveri_sop_overlap_on_excursion_date(pack):
    """T-KAVERI Temperature Excursion Management has overlapping Rev 01/02/03 windows."""
    hit = sop_in_force(
        pack.sops, "T-KAVERI", "Temperature Excursion Management", date(2026, 7, 28)
    )
    assert hit is not None
    assert hit.overlap_conflict is True
    assert len(hit.competing) >= 2
    # Highest rev selected
    assert "03" in str(hit.record.get("revision")) or "3" in str(hit.record.get("revision"))


def test_parse_2_8_variants():
    assert parse_storage_range("2-8 °C") == (2.0, 8.0)
    assert parse_storage_range("+2/+8 C") == (2.0, 8.0)
    assert parse_storage_range("Store at 2–8°C. Do not freeze.") == (2.0, 8.0)
    low, high = parse_storage_range("CRT 15-25C")
    assert low == 15.0 and high == 25.0


def test_aura_sop_single_rev_on_date(pack):
    hit = sop_in_force(
        pack.sops, "T-AURA", "Temperature Excursion Management", date(2025, 8, 14)
    )
    # AUD-2603 disposition date — must be able to answer which rev was in force
    assert hit is not None
    assert hit.record.get("doc_id")
