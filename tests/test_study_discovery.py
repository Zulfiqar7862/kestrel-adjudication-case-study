"""Study discovery is an auditable evidence search, not permission to release."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kestrel.api.app import create_app
from kestrel.config import _DEFAULT_PACK
from kestrel.engine import AdjudicationEngine
from kestrel.ingest import DataPack
from kestrel.rules.identity import ResolvedProduct
from kestrel.rules.stability import StabilityResolver
from tests._base import _make_tmp_svc


def product(**patch):
    args = dict(
        tenant_code="T",
        match_method="sku_exact",
        confidence=1,
        brand="Medicine 100U pen",
        presentation_hint="pen",
        internal_sku="P",
        storage_spec_text="2-8 C",
        stability_study_ref="NEW-REFERENCE",
        release_identity_eligible=True,
    )
    args.update(patch)
    return ResolvedProduct(**args)


def study(**patch):
    row = dict(
        tenant_code="T",
        study_ref="NEW-REFERENCE",
        product_text_as_written="Medicine 100U pen",
        study_type="Excursion / thermal cycling",
        readable="Y",
        permitted_excursion_text="6 h to 15 C",
        _source_sheet="06_Stability_Index",
        _source_row=2,
        approval_status="APPROVED",
        effective_from="2025-01-01",
        effective_to="2027-01-01",
        known_from="2025-01-01",
        superseded="N",
    )
    row.update(patch)
    return row


def discover(rows=None, p=None, **patch):
    resolver = StabilityResolver(DataPack(path=Path("synthetic"), stability=rows if rows is not None else [study()]))
    args = dict(
        knowledge_date=date(2026, 1, 1),
        event_date=date(2026, 1, 1),
        min_temp_c=4,
        max_temp_c=12,
        duration_min=15,
        sop_authority="ESTABLISHED",
    )
    args.update(patch)
    return resolver.discover(p or product(), **args)


def codes(candidate):
    return {str(r.code.value) for r in candidate.rejections}


def test_generic_cited_study_can_be_selected_with_complete_explicit_evidence():
    audit = discover()
    assert audit.selected_study_ref == "NEW-REFERENCE"
    assert audit.candidates[0].status == "SELECTED"
    assert not audit.candidates[0].rejections
    assert audit.candidates[0].source_row == 2


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"product_text_as_written": "Other 100U pen"}, "WRONG_PRODUCT"),
        ({"product_text_as_written": "Medicine 200U pen"}, "STRENGTH_MISMATCH"),
        ({"product_text_as_written": "Medicine 100U vial"}, "PRESENTATION_MISMATCH"),
        ({"product_text_as_written": "Medicine pen"}, "STRENGTH_UNKNOWN"),
        ({"product_text_as_written": "Medicine 100U"}, "PRESENTATION_UNKNOWN"),
        ({"study_type": "Long-term"}, "NOT_EXCURSION_STUDY"),
        ({"readable": "Partial"}, "UNREADABLE"),
        ({"approval_status": None}, "APPROVAL_UNKNOWN"),
        ({"approval_status": "DRAFT"}, "NOT_APPROVED"),
        ({"effective_from": None}, "EFFECTIVITY_UNKNOWN"),
        ({"effective_from": "2026-02-01"}, "NOT_EFFECTIVE"),
        ({"effective_to": "2025-02-01"}, "NOT_EFFECTIVE"),
        ({"known_from": None}, "KNOWLEDGE_TIME_UNKNOWN"),
        ({"known_from": "2026-02-01"}, "NOT_KNOWN_AT_TIME"),
        ({"superseded": "Y"}, "SUPERSEDED"),
        ({"superseded": None}, "SUPERSESSION_UNKNOWN"),
        ({"permitted_excursion_text": None}, "ALLOWANCE_MISSING"),
        ({"permitted_excursion_text": "Refer QA"}, "REQUIRES_QA"),
        ({"permitted_excursion_text": "unrecognized prose"}, "ALLOWANCE_UNPARSEABLE"),
    ],
)
def test_every_rejected_study_has_typed_explicit_reasons(patch, reason):
    audit = discover([study(**patch)])
    assert audit.selected_study_ref is None
    assert audit.candidates[0].status == "REJECTED"
    assert reason in codes(audit.candidates[0])


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"max_temp_c": 16}, "TEMPERATURE_NOT_COVERED"),
        ({"min_temp_c": 1}, "TEMPERATURE_RANGE_UNKNOWN"),
        ({"max_temp_c": None}, "TEMPERATURE_MISSING"),
        ({"duration_min": 361}, "DURATION_NOT_COVERED"),
        ({"duration_min": None}, "DURATION_MISSING"),
        ({"sop_authority": "CONFLICT"}, "CONFLICTING_SOP"),
        ({"sop_authority": "UNKNOWN"}, "SOP_AUTHORITY_UNKNOWN"),
        ({"knowledge_date": None}, "KNOWLEDGE_TIME_UNKNOWN"),
    ],
)
def test_event_coverage_and_authority_are_not_inferred(patch, reason):
    audit = discover(**patch)
    assert reason in codes(audit.candidates[0])
    assert audit.selected_study_ref is None


def test_unresolved_identity_blocks_study_selection():
    audit = discover(p=product(release_identity_eligible=False))
    assert "IDENTITY_UNRESOLVED" in codes(audit.candidates[0])


def test_discovery_records_all_tenant_rows_not_just_citation():
    audit = discover(
        [
            study(),
            study(study_ref="ALTERNATE", _source_row=3),
            study(study_ref="BAD", product_text_as_written="Other vial", _source_row=4),
        ]
    )
    assert len(audit.candidates) == 3
    assert "UNCITED_MAPPING_UNKNOWN" in codes(audit.candidates[1])
    assert "WRONG_PRODUCT" in codes(audit.candidates[2])
    assert audit.selected_study_ref == "NEW-REFERENCE"


def test_wrong_tenant_is_excluded_without_disclosing_foreign_evidence():
    rows = [study(tenant_code="OTHER", product_text_as_written="SECRET")]
    audit = discover(rows)
    assert audit.selected_study_ref is None
    assert "CITED_STUDY_OUTSIDE_TENANT_SCOPE" in [r.code.value for r in audit.reasons]
    assert "SECRET" not in str(asdict(audit)) and "OTHER" not in str(asdict(audit))
    assert audit.candidates == []


def test_duplicate_citation_is_not_first_row_wins():
    audit = discover([study(), study(_source_row=3)])
    assert audit.selected_study_ref is None
    assert all("AMBIGUOUS_CITATION" in codes(c) for c in audit.candidates)


@pytest.mark.parametrize("prior,reason", [(None, "CUMULATIVE_HISTORY_UNKNOWN"), (6, "CUMULATIVE_EXCEEDED")])
def test_cumulative_cannot_use_only_current_excursion(prior, reason):
    audit = discover([study(permitted_excursion_text="6 h to 15 C cumulative")], prior_exposure_hours=prior)
    assert reason in codes(audit.candidates[0])
    assert audit.selected_study_ref is None


def test_above_label_threshold_is_not_a_maximum_temperature():
    audit = discover(
        [study(permitted_excursion_text="Cumulative 72 h above 8 C permitted across shelf life")],
        prior_exposure_hours=0,
    )
    assert "TEMPERATURE_RANGE_UNKNOWN" in codes(audit.candidates[0])


def test_strict_below_is_not_inclusive():
    audit = discover([study(permitted_excursion_text="One excursion, up to 6 h below 15 C")], max_temp_c=15)
    assert "TEMPERATURE_NOT_COVERED" in codes(audit.candidates[0])


def test_real_index_missing_approval_and_dates_is_explicit_not_guessed():
    pack = DataPack.load(_DEFAULT_PACK)
    result = AdjudicationEngine(pack).adjudicate(pack.event_by_id("EXC-107133"))
    audit = result.study_discovery
    own = [r for r in pack.stability if r["tenant_code"] == result.tenant_code]
    assert len(audit["candidates"]) == len(own)
    assert audit["selected_study_ref"] is None
    assert result.evidence["stability"]["discovery"] == audit
    assert all(c["source_sheet"] == "06_Stability_Index" and c["source_row"] for c in audit["candidates"])
    assert all("APPROVAL_UNKNOWN" in [r["code"] for r in c["rejections"]] for c in audit["candidates"])


def test_sealed_api_openapi_and_rendered_ui_share_discovery(tmp_path):
    import json
    import subprocess

    svc = _make_tmp_svc(tmp_path)
    record = svc.adjudicate_event("EXC-107133")
    result, bundle = record["result"], record["bundle"]
    sealed = svc.evidence.get(bundle["bundle_id"], tenant_code=result.tenant_code)
    assert sealed["inputs"]["expected_result"]["study_discovery"] == result.study_discovery
    client = TestClient(create_app(svc))
    payload = client.get("/events/EXC-107133").json()
    assert payload["study_discovery"] == result.study_discovery
    schema = client.get("/openapi.json").json()
    assert "StudyRejectionCode" in schema["components"]["schemas"]
    assert "STRENGTH_MISMATCH" in json.dumps(schema)
    html = Path("src/kestrel/api/static/index.html").read_text()
    start = html.index("function studyPanel(")
    end = html.index("\nfunction ", start + 1)
    js = html[start:end]
    audit = result.study_discovery
    audit["candidates"][0]["study_ref"] = "<script>BAD</script>"
    rendered = subprocess.check_output(
        [
            "node",
            "-e",
            "function esc(x){return String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;')}\n"
            + js
            + "\nconsole.log(studyPanel("
            + json.dumps(audit)
            + "));",
        ],
        text=True,
    )
    assert "APPROVAL_UNKNOWN" in rendered
    assert "&lt;script&gt;" in rendered and "<script>BAD" not in rendered


@pytest.mark.parametrize("key", ["effective_from", "effective_to", "known_from"])
def test_malformed_authority_dates_are_unknown_not_crashes(key):
    audit = discover([study(**{key: "not-a-date"})])
    assert audit.selected_study_ref is None
    assert any(r.assessment == "UNKNOWN" for r in audit.candidates[0].rejections)


@pytest.mark.parametrize("text", ["One excursion, up to 6 h below 15 C", "Single excursion 6 h to 15 C"])
def test_single_use_language_requires_history_even_without_word_once(text):
    audit = discover([study(permitted_excursion_text=text)])
    assert "ONCE_ONLY_HISTORY_UNKNOWN" in codes(audit.candidates[0])
    assert audit.selected_study_ref is None


@pytest.mark.parametrize("field", ["min_temp_c", "max_temp_c", "duration_min"])
def test_nonfinite_event_measurements_never_select(field):
    audit = discover(**{field: float("nan")})
    assert audit.selected_study_ref is None


def test_foreign_candidate_helper_redacts_all_material():
    from kestrel.rules.study_discovery import evaluate_candidate

    c = evaluate_candidate(
        study(tenant_code="SECRET", study_ref="SECRET"),
        product(),
        cited_count=1,
        knowledge_date=date(2026, 1, 1),
        event_date=date(2026, 1, 1),
        min_temp_c=4,
        max_temp_c=12,
        duration_min=15,
        sop_authority="ESTABLISHED",
        prior_exposure_hours=None,
    )
    assert "WRONG_TENANT" in codes(c)
    assert "SECRET" not in str(asdict(c))


def test_rendered_positive_selection_includes_selected_reference(tmp_path):
    import json
    import subprocess

    html = Path("src/kestrel/api/static/index.html").read_text()
    start = html.index("function studyPanel(")
    end = html.index("\nfunction ", start + 1)
    audit = asdict(discover())
    script = (
        "function esc(x){return String(x??'')}\n"
        + html[start:end]
        + "\nconsole.log(studyPanel("
        + json.dumps(audit)
        + "));"
    )
    rendered = subprocess.check_output(["node", "-e", script], text=True)
    assert "selected: NEW-REFERENCE" in rendered
    assert "SELECTED" in rendered


def test_cited_candidate_rejection_details_reach_engine_rationale():
    from tests.test_review_regressions import fixture

    p, event = fixture(max_c=20, firmware="other")
    p.stability[0]["permitted_excursion_text"] = "No excursion above 25 C permitted"
    result = AdjudicationEngine(p).adjudicate(event)
    assert any("ALLOWANCE_UNPARSEABLE" in line and "no duration" in line for line in result.rationale)


@pytest.mark.parametrize("min_c,max_c,expected", [(-0.1, 6, "DESTROY"), (3, 20, "DESTROY")])
def test_existing_conditional_arithmetic_is_preserved_below_discovery_gate(min_c, max_c, expected):
    # Deliberately supplied facts test existing arithmetic, not study qualification.
    from kestrel.decision_rules import decide
    from tests.test_decision_rules import make_facts, stability

    facts = make_facts(
        min_c=min_c, corrected_max_c=max_c, stability=stability(no_excursion=True), label_low_c=2, label_high_c=8
    )
    verdict, _trace = decide(facts)
    assert verdict.disposition == expected


def test_excel_datetime_authority_values_do_not_crash():
    from datetime import datetime

    audit = discover(
        [study(effective_from=datetime(2025, 1, 1), effective_to=datetime(2027, 1, 1), known_from=datetime(2025, 1, 1))]
    )
    assert audit.selected_study_ref == "NEW-REFERENCE"


def test_contradictory_pen_suffix_cannot_hide_behind_pfs_precedence():
    audit = discover(
        [study(product_text_as_written="Medicine 100U PFS — pen")],
        p=product(brand="Medicine 100U PFS", presentation_hint="pfs"),
    )
    assert audit.selected_study_ref is None
    assert "PRESENTATION_MISMATCH" in codes(audit.candidates[0])


def test_no_selection_never_claims_not_cumulative_per_selected_study():
    from tests.test_review_regressions import fixture

    p, event = fixture(max_c=20, firmware="other")
    result = AdjudicationEngine(p).adjudicate(event)
    assert result.study_discovery["selected_study_ref"] is None
    assert "unresolved" in result.evidence["stability"]["cumulative_assessment"]
    assert "per selected study" not in result.evidence["stability"]["cumulative_assessment"]
