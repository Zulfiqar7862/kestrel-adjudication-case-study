"""Fail-closed regressions for the independent correctness review."""

from dataclasses import replace
from datetime import date

import pytest

from kestrel.decision_rules import AUTO_CLOSE, ESCALATE, decide, is_out_of_range
from tests.test_decision_rules import make_facts, stability


@pytest.mark.parametrize("maximum,minimum", [(None, None), (None, 5), (7, None)])
def test_incomplete_temperature_range_is_unknown(maximum, minimum):
    assert is_out_of_range(maximum, minimum, 2, 8) is None


@pytest.mark.parametrize("triage", ["", "Duplicate", "Facility equipment event", "Sensor artefact"])
@pytest.mark.parametrize("maximum,minimum", [(None, None), (None, 5), (7, None)])
def test_missing_temperatures_cannot_be_bypassed_by_triage(triage, maximum, minimum):
    facts = make_facts(
        corrected_max_c=maximum,
        min_c=minimum,
        event={"triage_outcome": triage, "gateway_gap_min": 90, "interpolated": "Y"},
    )
    verdict, trace = decide(facts)
    assert verdict.disposition == ESCALATE
    assert "insufficient temperature evidence" in " ".join(trace).lower()


def test_complete_extrema_do_not_require_mean():
    assert decide(make_facts(corrected_max_c=7))[0].disposition == AUTO_CLOSE


@pytest.fixture(scope="module")
def pack():
    from kestrel.config import _DEFAULT_PACK
    from kestrel.ingest import DataPack

    return DataPack.load(_DEFAULT_PACK)


def test_afx_de_exact_alias_beats_indian_substring(pack):
    from kestrel.rules.identity import IdentityResolver

    row, error = IdentityResolver(pack).resolve_carrier_contract("AFX-DE", date(2026, 7, 28))
    assert error is None
    assert row["contract_id"] == "CNT-2023-0441"


def test_carrier_ambiguous_alias_is_unresolved(pack):
    from copy import deepcopy

    from kestrel.rules.identity import IdentityResolver

    copied = deepcopy(pack)
    # Deliberate conflict: the same exact alias is claimed by two legal entities.
    for row in copied.carriers[:2]:
        row["names_seen_on_documents"] = "CONFLICT"
        row["_effective_from"] = row["_effective_to"] = None
    row, error = IdentityResolver(copied).resolve_carrier_contract("CONFLICT", date(2026, 7, 28))
    assert row is None
    assert "ambiguous" in error.lower()


def test_carrier_exact_legal_entity_beats_alias(pack):
    from copy import deepcopy

    from kestrel.rules.identity import IdentityResolver

    copied = deepcopy(pack)
    first, second = copied.carriers[:2]
    for row in [first, second]:
        row["_effective_from"] = row["_effective_to"] = None
    first["counterparty_legal_entity"] = "Exact Legal"
    second["names_seen_on_documents"] = "Exact Legal"
    row, error = IdentityResolver(copied).resolve_carrier_contract("Exact Legal", date(2026, 7, 28))
    assert error is None
    assert row["contract_id"] == first["contract_id"]


@pytest.mark.parametrize("cumulative,above", [(True, False), (False, True)])
@pytest.mark.parametrize("triage,gap", [("", 0), ("Duplicate", 0), ("Facility equipment event", 0), ("", 90)])
def test_cumulative_history_unresolved_before_earlier_rules(cumulative, above, triage, gap):
    facts = make_facts(
        stability=stability(max_duration_hours=72, max_temp_c=25, cumulative=cumulative, cumulative_above_label=above),
        event={
            "triage_outcome": triage,
            "gateway_gap_min": gap,
            "interpolated": "Y",
            "batch_id": "UNVERIFIED",
            "prior_exposure_hours": 0,
        },
        duration_min=15,
    )
    verdict, trace = decide(facts)
    assert verdict.disposition == ESCALATE
    assert "cumulative assessment unresolved" in " ".join(trace).lower()


def test_cumulative_allowance_does_not_prevent_proven_in_range_closure():
    facts = make_facts(corrected_max_c=7, stability=stability(max_duration_hours=72, cumulative=True))
    assert decide(facts)[0].disposition == AUTO_CLOSE


def test_mismatched_study_never_uses_master_allowance(pack):
    from kestrel.rules.identity import IdentityResolver
    from kestrel.rules.stability import StabilityResolver

    product = IdentityResolver(pack).resolve_product("T-KAVERI", "08901234500035")
    position = StabilityResolver(pack).resolve(product)
    assert position.source == "unresolved"
    assert position.max_duration_hours is None
    assert position.presentation_mismatch_risk


@pytest.mark.parametrize(
    "change", ["missing-study", "wrong-product", "wrong-type", "unknown-presentation", "duplicate-reference"]
)
def test_study_applicability_must_be_established(pack, change):
    from copy import deepcopy

    from kestrel.rules.identity import ResolvedProduct
    from kestrel.rules.stability import StabilityResolver

    copied = deepcopy(pack)
    product = ResolvedProduct(
        tenant_code="T",
        match_method="sku_exact",
        confidence=1,
        brand="Medicine 100U pen",
        presentation_hint="pen",
        stability_study_ref="S",
        permitted_excursion_text="6 h to 15 C",
    )
    row = dict(
        tenant_code="T",
        study_ref="S",
        product_text_as_written="Medicine 100U pen",
        study_type="Excursion / thermal cycling",
        readable="Y",
        permitted_excursion_text="6 h to 15 C",
    )
    copied.stability = [row]
    if change == "missing-study":
        copied.stability = []
    elif change == "wrong-product":
        row["product_text_as_written"] = "Other 100U pen"
    elif change == "wrong-type":
        row["study_type"] = "Accelerated"
    elif change == "unknown-presentation":
        row["product_text_as_written"] = "Medicine 100U"
    elif change == "duplicate-reference":
        copied.stability.append(dict(row))
    result = StabilityResolver(copied).resolve(product)
    assert result.source == "unresolved"
    assert result.max_duration_hours is None


def test_sop_overlap_blocks_release_even_with_otherwise_usable_evidence():
    verdict, trace = decide(make_facts(sop_overlap=True, duration_min=5))
    assert verdict.disposition == ESCALATE
    assert "sop" in " ".join(trace).lower()


@pytest.mark.parametrize("mode", ["missing", "site-annexure", "overlap"])
def test_engine_sop_authority_blocks_early_gap_release(pack, mode):
    from copy import deepcopy

    from kestrel.engine import AdjudicationEngine

    copied = deepcopy(pack)
    # Isolate SOP authority from cumulative/mismatched study failures.
    copied.products = [
        dict(
            tenant_code="T",
            internal_sku="P",
            brand_as_labelled="Medicine pen",
            storage_spec_text="2-8 C",
            stability_study_ref="S",
        )
    ]
    copied.stability = [
        dict(
            tenant_code="T",
            study_ref="S",
            product_text_as_written="Medicine pen",
            study_type="Excursion / thermal cycling",
            readable="Y",
            permitted_excursion_text="6 h to 15 C",
        )
    ]
    copied.sops = (
        []
        if mode == "missing"
        else [
            dict(
                tenant_code="T",
                title="Temperature Excursion Management",
                doc_id="D",
                revision="Rev 01",
                _effective_from=date(2020, 1, 1),
                _effective_to=None,
                applies_to_facilities_text="Site-specific — see Annexure 2",
                acceptance_limits_location="Annexure 2",
            )
        ]
    )
    if mode == "overlap":
        copied.sops.append(dict(copied.sops[0], revision="Rev 02"))
    event = dict(
        pack.event_by_id("EXC-107133"),
        tenant_code="T",
        product_ref_as_received="P",
        gateway_gap_min=90,
        interpolated="Y",
    )
    result = AdjudicationEngine(copied).adjudicate(event)
    assert result.recommendation == ESCALATE
    assert any(
        "sop" in text.lower() and ("unresolved" in text.lower() or "missing" in text.lower())
        for text in result.rationale
    )


def test_exc_107133_not_forced_to_history(pack):
    from kestrel.engine import AdjudicationEngine

    result = AdjudicationEngine(pack).adjudicate(pack.event_by_id("EXC-107133"))
    assert result.recommendation == ESCALATE
    assert result.evidence["stability"]["source"] == "unresolved"


@pytest.mark.parametrize(
    "maximum,minimum,low,high",
    [
        (float("nan"), 5, 2, 8),
        (8, float("inf"), 2, 8),
        (5, 7, 2, 8),
        (7, 5, None, 8),
        (7, 5, 8, 2),
    ],
)
def test_invalid_temperatures_or_label_are_not_safe(maximum, minimum, low, high):
    assert is_out_of_range(maximum, minimum, low, high) is None
    assert (
        decide(make_facts(corrected_max_c=maximum, min_c=minimum, label_low_c=low, label_high_c=high))[0].disposition
        == ESCALATE
    )


def test_positive_study_applicability_not_hard_coded():
    from pathlib import Path

    from kestrel.ingest import DataPack
    from kestrel.rules.identity import ResolvedProduct
    from kestrel.rules.stability import StabilityResolver

    product = ResolvedProduct(
        "T", "sku_exact", 1, brand="Medicine pen", presentation_hint="pen", stability_study_ref="NEW-REFERENCE"
    )
    pack = DataPack(
        path=Path("synthetic"),
        stability=[
            dict(
                tenant_code="T",
                study_ref="NEW-REFERENCE",
                product_text_as_written="Medicine pen",
                study_type="Excursion / thermal cycling",
                readable="Y",
                permitted_excursion_text="6 h to 15 C",
            )
        ],
    )
    result = StabilityResolver(pack).resolve(product)
    assert result.source == "stability_index"
    assert result.max_duration_hours == 6
    assert result.max_temp_c == 15
    assert result.authority_issue is None


def test_ambiguous_carrier_is_preserved_in_engine_evidence(pack):
    from copy import deepcopy

    from kestrel.engine import AdjudicationEngine

    copied = deepcopy(pack)
    for row in copied.carriers[:2]:
        row["names_seen_on_documents"] = "CONFLICT"
        row["_effective_from"] = row["_effective_to"] = None
    result = AdjudicationEngine(copied).adjudicate(
        dict(pack.event_by_id("EXC-107133"), carrier_ref_as_received="CONFLICT")
    )
    assert result.carrier_contract_id is None
    assert "ambiguous" in result.evidence["carrier"]["error"]
    assert any("ambiguous carrier" in text for text in result.rationale)


@pytest.mark.parametrize("path", ["gateway", "ultra-cold", "fallback", "allowance-closure"])
@pytest.mark.parametrize("authority", ["missing-sop", "revision-overlap"])
def test_every_release_path_and_allowance_closure_has_final_authority_gate(path, authority):
    facts = make_facts(duration_min=5)
    if path == "gateway":
        facts = replace(facts, event={"gateway_gap_min": 90, "interpolated": "Y"})
    elif path == "ultra-cold":
        facts = replace(facts, label_low_c=-80, label_high_c=-60, min_c=-80, corrected_max_c=-40)
    elif path == "allowance-closure":
        facts = replace(facts, stability=stability(max_duration_hours=6, max_temp_c=15))
    facts = replace(
        facts,
        sop_authority_issue="governing SOP missing" if authority == "missing-sop" else None,
        sop_overlap=authority == "revision-overlap",
    )
    verdict, trace = decide(facts)
    assert verdict.disposition == ESCALATE
    assert "release authority unresolved" in " ".join(trace)


def test_carrier_ambiguous_substring_cannot_use_longest_name(pack):
    from copy import deepcopy

    from kestrel.rules.identity import IdentityResolver

    copied = deepcopy(pack)
    copied.carriers = copied.carriers[:2]
    for index, row in enumerate(copied.carriers):
        row["names_seen_on_documents"] = f"common-code-{index}"
        row["counterparty_legal_entity"] = "Long Legal Entity" if index else "Short"
        row["_effective_from"] = row["_effective_to"] = None
    row, error = IdentityResolver(copied).resolve_carrier_contract("common-code", date(2026, 7, 28))
    assert row is None
    assert "ambiguous" in error
    assert "substring" in error


def test_unique_carrier_substring_is_candidate_not_verified_identity(pack):
    from copy import deepcopy

    from kestrel.rules.identity import IdentityResolver

    copied = deepcopy(pack)
    copied.carriers = copied.carriers[:1]
    copied.carriers[0].update(names_seen_on_documents="Unique Shipping Alias", _effective_from=None, _effective_to=None)
    row, error = IdentityResolver(copied).resolve_carrier_contract("Unique Shipping", date(2026, 7, 28))
    assert row is None
    assert "CARRIER_SUBSTRING_NOT_IDENTITY" in error
    result = IdentityResolver(copied).resolve_carrier("T-KAVERI", "Unique Shipping", date(2026, 7, 28))
    assert result.candidates[0]["contract_id"] == copied.carriers[0]["contract_id"]
    assert result.links[0].verification_status == "UNVERIFIED"
    assert result.release_identity_eligible is False
