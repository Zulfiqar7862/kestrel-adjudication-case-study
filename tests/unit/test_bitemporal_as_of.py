from datetime import date


def test_aura_sop_as_of_audit_date(tmp_svc):
    """AUD-2603: SOP in force at origin on 2025-08-14 must be answerable."""
    hit = tmp_svc.store.sop_in_force(
        "T-AURA", "Temperature Excursion Management", date(2025, 8, 14)
    )
    assert hit["record"] is not None
    assert hit["record"]["payload"]["doc_id"]
    vf = hit["record"]["valid_from"][:10]
    assert vf <= "2025-08-14"


def test_kaveri_sop_overlap(tmp_svc):
    hit = tmp_svc.store.sop_in_force(
        "T-KAVERI", "Temperature Excursion Management", date(2026, 7, 28)
    )
    assert hit["record"] is not None
    assert hit["overlap_conflict"] is True
