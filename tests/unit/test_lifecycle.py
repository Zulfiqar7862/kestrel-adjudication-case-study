from kestrel_sentinel.domain.enums import CaseState, Disposition, TransitionError


def test_lifecycle_sign_and_reopen_months_later(tmp_svc):
    out = tmp_svc.adjudicate_event("EXC-107133", persist=True)
    case = out["case"]
    assert case["state"] in {
        CaseState.AWAITING_REVIEWER.value,
        CaseState.TRIAGED_NON_ACTIONABLE.value,
        CaseState.REOPENED.value,
    }
    # Force to awaiting then sign
    if case["state"] != CaseState.AWAITING_REVIEWER.value:
        # auto path — open as recommended via transition if possible
        pass
    signed = tmp_svc.lifecycle.sign(
        case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE
    ) if case["state"] == CaseState.AWAITING_REVIEWER.value else None
    if signed is None:
        # transition manually
        c = tmp_svc.lifecycle.transition(case["case_id"], CaseState.AWAITING_REVIEWER) if case["state"] == CaseState.TRIAGED_NON_ACTIONABLE.value else case
        # TRIAGED can't go to AWAITING directly - check ALLOWED
        try:
            signed = tmp_svc.lifecycle.sign(case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE)
        except TransitionError:
            tmp_svc.lifecycle.transition(case["case_id"], CaseState.RECOMMENDED)
            tmp_svc.lifecycle.transition(case["case_id"], CaseState.AWAITING_REVIEWER)
            signed = tmp_svc.lifecycle.sign(case["case_id"], "QA-IN-04", Disposition.RELEASE_WITH_NOTE)
    assert signed["state"] == CaseState.CLOSED_SIGNED.value
    assert signed["signed_by"] == "QA-IN-04"

    # Reopen months later (bulletin)
    revision = tmp_svc.lifecycle.reopen(signed["case_id"], "BULLETIN_TT_CB_114")
    assert revision["reopened_from_case_id"] == signed["case_id"]
    assert revision["state"] == CaseState.REOPENED.value
    prior = tmp_svc.store.get_case(signed["case_id"])
    assert prior["state"] == CaseState.REOPENED.value


def test_queue_orders_by_reg_deadline(tmp_svc):
    # Persist a handful
    for eid in ["EXC-107133", "EXC-110637", "EXC-110651"]:
        if tmp_svc.pack.event_by_id(eid):
            tmp_svc.adjudicate_event(eid, persist=True)
    q = tmp_svc.lifecycle.storm_safe_queue(limit=50)
    deadlines = [c.get("reg_deadline_utc") or "9999" for c in q if c.get("regulator_reportable")]
    assert deadlines == sorted(deadlines)
