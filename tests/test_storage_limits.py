"""Regression specifications for explicit bounds, evidence sufficiency and triage provenance."""

import pytest

from kestrel.decision_rules import AUTO_CLOSE, ESCALATE, decide
from kestrel.engine import AdjudicationEngine
from kestrel.rules import as_of
from tests.test_decision_rules import make_facts
from tests.test_review_regressions import fixture


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2°C – 8°C", (2.0, 8.0)),
        ("15°C to 25°C (excursions to 30°C permitted, see stability)", (15.0, 25.0)),
        ("-80C to -60C (dry ice permitted)", (-80.0, -60.0)),
        ("-80 to -60 °C", (-80.0, -60.0)),
        ("FROZEN (-25,-15)", (-25.0, -15.0)),
        ("Below 25 °C", (None, 25.0)),
        ("≤ −150 °C vapour phase LN2", (None, -150.0)),
        ("LN2 vapour phase (-196 nominal)", (None, None)),
        ("Controlled room temperature", (None, None)),
    ],
)
def test_storage_spelling_without_invented_bounds(text, expected):
    assert as_of.parse_storage_range(text) == expected


@pytest.mark.parametrize(
    "text,kind,lower,upper",
    [
        ("2-8 °C", "two_sided", (2, True), (8, True)),
        ("Below 25 °C", "upper_only", None, (25, False)),
        ("≤ −150 °C", "upper_only", None, (-150, True)),
        ("Above 2 C", "lower_only", (2, False), None),
    ],
)
def test_explicit_bound_metadata(text, kind, lower, upper):
    result = as_of.parse_storage_limits(text)
    assert result.bound_type == kind
    assert (None if result.lower is None else (result.lower.value_c, result.lower.inclusive)) == lower
    assert (None if result.upper is None else (result.upper.value_c, result.upper.inclusive)) == upper
    assert result.unresolved_reason is None


def result_for(text, minimum=3, maximum=7, **extra):
    pack, event = fixture(min_c=3, max_c=7, firmware="other")
    pack.products[0]["storage_spec_text"] = text
    pack.stability = []  # No study authority: out-of-range cases need QA, not a clinical fate.
    pack.products[0]["stability_study_ref"] = None  # Avoid the orthogonal unreadable-citation rule.
    event.update(min_temp_c=minimum, max_temp_c=maximum, **extra)
    return AdjudicationEngine(pack).adjudicate(event)


@pytest.mark.parametrize(
    "text,minimum,maximum,expected",
    [
        ("2-8 C", 2, 8, AUTO_CLOSE),
        ("2-8 C", 1.999, 8, ESCALATE),
        ("2-8 C", 2, 8.001, ESCALATE),
        ("Below 25 C", 20, 24.999, AUTO_CLOSE),
        ("Below 25 C", 20, 25, ESCALATE),
        ("≤ −150 °C", -180, -150, AUTO_CLOSE),
        ("≤ −150 °C", -180, -149.999, ESCALATE),
        ("Above 2 C", 2, 7, ESCALATE),
        ("Above 2 C", 2.001, 7, AUTO_CLOSE),
        ("≥ 2 C", 2, 7, AUTO_CLOSE),
        ("≤ 25 C", None, 25, AUTO_CLOSE),
    ],
)
def test_equality_and_strictness_at_each_boundary(text, minimum, maximum, expected):
    assert result_for(text, minimum, maximum).recommendation == expected


@pytest.mark.parametrize(
    "text,minimum,maximum",
    [
        ("Below 25 C", 20, None),
        ("Below 25 C", None, None),
        ("Above 2 C", None, 7),
        ("2-8 C", None, 7),
        ("2-8 C", 3, None),
        ("Below 25 C", 20, float("nan")),
        ("Below 25 C", 26, 24),
    ],
)
def test_missing_required_or_invalid_measurements_are_not_safety_evidence(text, minimum, maximum):
    result = result_for(text, minimum, maximum, mean_temp_c=5, triage_outcome="Duplicate")
    assert result.recommendation == ESCALATE
    assert result.triage_label == "ACTIONABLE — insufficient temperature evidence"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "2--8 C",
        "8-2 C",
        "Below maybe 25 C",
        "25 C",
        "Controlled room temperature",
        "LN2 nominal -196 C",
        "2-8 C or 15-25 C",
    ],
)
def test_malformed_or_ambiguous_storage_is_distinct_from_missing_measurements(text):
    result = result_for(text)
    assert result.recommendation == ESCALATE
    assert result.triage_label == "ACTIONABLE — storage instructions unresolved"
    assert result.evidence["labelled_range"]["unresolved_reason"]


def test_extra_constraints_are_preserved_without_becoming_numeric_bounds():
    limits = as_of.parse_storage_limits("Below 25 C. Do not freeze. Protect from light.")
    assert limits.lower is None
    assert limits.upper.value_c == 25
    assert not limits.upper.inclusive
    assert limits.constraints == ("do not freeze", "protect from light")
    result = result_for("2-8 C (protect from light)")
    assert result.evidence["labelled_range"]["constraints"] == ["protect from light"]
    assert "not independently verified" in " ".join(result.rationale)


@pytest.mark.parametrize("triage", ["Duplicate", "Facility equipment event", "Sensor artefact", "dock door"])
def test_historical_autoclose_has_explicit_unverified_provenance(triage):
    facts = make_facts(corrected_max_c=8, event={"triage_outcome": triage, "dock_door_open_flag": "Y"}, duration_min=10)
    verdict, trace = decide(facts)
    assert verdict.disposition == AUTO_CLOSE
    assert any(
        "unverified historical classification" in line.lower() and "not independent" in line.lower() for line in trace
    )


def test_decimal_comma_is_not_silently_a_two_sided_range():
    assert as_of.parse_storage_limits("2,8 C").bound_type == "unresolved"


def test_unitless_one_sided_instruction_is_not_assumed_celsius():
    limits = as_of.parse_storage_limits("Below 25")
    assert limits.bound_type == "unresolved"
    assert limits.upper is None
