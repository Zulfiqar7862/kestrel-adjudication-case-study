def test_shadow_bulletin_produces_diffs(tmp_svc):
    report = tmp_svc.shadow_bulletin()
    assert report["candidates"] > 0
    assert "TT-CB-114" in report["change"] or "bulletin" in report["change"].lower()
    # At least some rows should differ when bulletin removed
    assert isinstance(report["diff_rows"], list)
