def test_exc_107133_release_with_note(tmp_svc):
    out = tmp_svc.adjudicate_event("EXC-107133", persist=True)
    assert out["result"].recommendation == "RELEASE_WITH_NOTE"
    assert out["bundle"]["bundle_id"].startswith("EVB-")
    assert out["bundle"]["inputs"]["resolution"]["product"]["gtin"] == "08901234500035"
