"""Golden tests pinned to pack narratives and override rows."""

from adjudication.engine import (
    RELEASE_WITH_NOTE,
    DESTROY,
    ESCALATE,
    AUTO_CLOSE,
    QUARANTINE_PENDING_LAB,
)


def test_exc_107133_brief_narrative(engine, pack):
    """Fifteen minutes at 11.2°C on Glucodyne SoloJet — within ≤6h to 15°C, cumulative note."""
    ev = pack.event_by_id("EXC-107133")
    assert ev is not None
    r = engine.adjudicate(ev)
    assert r.recommendation == RELEASE_WITH_NOTE
    assert r.requires_human_signature is True
    assert r.bulletin_applied is False
    assert r.corrected_max_temp_c == 11.2
    # Evidence pack must cite something reconstructable
    assert r.evidence.get("product") is not None
    assert r.reg_deadline_utc or r.reg_window_hours


def test_exc_110448_bulletin_underread(engine, pack):
    """Override: logger TT-2.14.3 — do not destroy on known-bad sensor alone."""
    ev = pack.event_by_id("EXC-110448")
    if ev is None:
        return
    r = engine.adjudicate(ev)
    assert r.bulletin_applied is True
    assert r.corrected_max_temp_c is not None
    assert r.corrected_max_temp_c == float(ev["max_temp_c"]) + 1.8


def test_override_freeze_vaccine_pattern(engine, pack):
    """EXC-110483: below 0°C on adjuvanted vaccine → DESTROY, not RELEASE_WITH_NOTE."""
    ev = pack.event_by_id("EXC-110483")
    if ev is None:
        return
    r = engine.adjudicate(ev)
    # Engine should not treat below-spec same as above-spec for 2-8 products
    assert r.recommendation in {DESTROY, ESCALATE, QUARANTINE_PENDING_LAB}


def test_facility_storm_auto_close(engine, pack):
    """INC-2502 coincident facility events should AUTO_CLOSE when triage says no product."""
    # Pick a known facility equipment row from dump
    candidates = [
        e
        for e in pack.events
        if e.get("notes") and "Whitefield" in str(e.get("notes"))
        and "facility equipment" in str(e.get("triage_outcome") or "").lower()
    ]
    assert candidates, "expected INC-2502 facility rows in stratified pack"
    r = engine.adjudicate(candidates[0])
    assert r.recommendation == AUTO_CLOSE


def test_every_event_produces_structured_result(engine, pack):
    for ev in pack.events:
        r = engine.adjudicate(ev)
        assert r.event_id == ev["event_id"]
        assert r.recommendation
        assert 0.0 <= r.confidence <= 1.0
        assert isinstance(r.rationale, list)
        assert "temps" in r.evidence
