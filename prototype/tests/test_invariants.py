"""Property / invariant tests — must hold for every pack row."""

from adjudication.engine import AUTO_CLOSE, ACTIONABLE_DISPOSITIONS


def test_auto_close_never_requires_human(engine, pack):
    for ev in pack.events:
        r = engine.adjudicate(ev)
        if r.recommendation == AUTO_CLOSE:
            assert r.requires_human_signature is False
        if r.recommendation in ACTIONABLE_DISPOSITIONS:
            assert r.requires_human_signature is True


def test_regulatory_deadline_after_alert_when_reportable(engine, pack):
    for ev in pack.events:
        if str(ev.get("regulator_reportable") or "").upper() != "Y":
            continue
        r = engine.adjudicate(ev)
        assert r.reg_window_hours is not None
        assert r.reg_deadline_utc is not None
        assert ev.get("_alert_ts") is not None
        assert r.reg_deadline_utc >= ev["_alert_ts"].isoformat(sep=" ")[:19]


def test_bulletin_correction_monotonic(engine, pack):
    for ev in pack.events:
        if str(ev.get("logger_fw")) != "TT-2.14.3":
            continue
        r = engine.adjudicate(ev)
        assert r.bulletin_applied
        if ev.get("max_temp_c") is not None:
            assert r.corrected_max_temp_c == float(ev["max_temp_c"]) + 1.8


def test_sop_as_of_never_returns_future_revision(engine, pack):
    """Selected SOP effective_from must be on or before excursion date."""
    from datetime import datetime

    checked = 0
    for ev in pack.events[:80]:
        r = engine.adjudicate(ev)
        if not r.sop_doc_id:
            continue
        as_of = (ev.get("_excursion_start") or ev.get("_alert_ts")).date()
        sop = r.evidence.get("sop") or {}
        ef = sop.get("effective_from")
        if ef and ef != "None":
            ef_d = datetime.strptime(ef, "%Y-%m-%d").date()
            assert ef_d <= as_of
            checked += 1
    assert checked > 0
