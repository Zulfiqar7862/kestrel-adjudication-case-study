"""Historical classifications are reference data, never independent closure authority."""

import json
import subprocess
from pathlib import Path

import pytest

from kestrel.api.app import create_app
from kestrel.decision_rules import AUTO_CLOSE, decide
from tests._base import _KestrelTestCase
from tests.test_decision_rules import make_facts

CANDIDATE = "HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED"


@pytest.mark.parametrize(
    "triage,maximum",
    [
        ("Duplicate", 10),
        ("Facility equipment event", 10),
        ("No product loaded", 7),
        ("Sensor artefact", 8.3),
        ("dock door", 10),
    ],
)
@pytest.mark.parametrize("claims_verified", [False, True])
def test_historical_text_cannot_authorize_autoclose(triage, maximum, claims_verified):
    event = {
        "triage_outcome": triage,
        "dock_door_open_flag": "Y",
        "duplicate_verified": claims_verified,
        "load_verified": claims_verified,
    }
    verdict, trace = decide(make_facts(event=event, corrected_max_c=maximum, duration_min=10))
    assert verdict.disposition == CANDIDATE
    assert verdict.disposition != AUTO_CLOSE
    assert "not independent" in " ".join(trace).lower()


class TestHistoricalCandidateSurfaces(_KestrelTestCase):
    def client(self):
        from fastapi.testclient import TestClient

        return TestClient(create_app(self.svc))

    def test_api_candidate_is_review_only_and_preserves_history(self):
        response = self.client().post("/adjudicate", json={"event_id": "EXC-112394"})
        assert response.status_code == 200
        body = response.json()
        assert body["recommendation"] == CANDIDATE
        assert body["case_state"] == "PENDING_EVIDENCE"
        assert body["requires_human_review"] is True
        assert body["requires_human_signature"] is True
        assert body["closure_eligibility"] == "historical_candidate_unverified"
        assert body["historical_classification"] == self.svc.pack.event_by_id("EXC-112394")["triage_outcome"]
        assert body["independent_closure_evidence"] == []
        detail = self.client().get("/events/EXC-112394").json()
        for key in [
            "historical_classification",
            "closure_eligibility",
            "requires_human_review",
            "independent_closure_evidence",
        ]:
            assert detail[key] == body[key]

    def test_openapi_declares_candidate_and_review_fields(self):
        schema = self.client().get("/openapi.json").json()
        response = schema["paths"]["/adjudicate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in response
        model = schema["components"]["schemas"][response["$ref"].split("/")[-1]]
        assert {
            "closure_eligibility",
            "historical_classification",
            "requires_human_review",
            "independent_closure_evidence",
        } <= set(model["properties"])
        assert CANDIDATE in schema["components"]["schemas"]["Disposition"]["enum"]

    def test_ui_renders_verified_and_historical_counts_separately(self):
        html = self.client().get("/ui").text
        assert 'data-metric="verified-auto-close">0</strong>' in html
        assert 'data-metric="historical-candidates">37</strong>' in html
        assert "Unverified historical candidate" in html
        assert CANDIDATE in html
        assert "not independently verified" in html
        assert "current.closure_eligibility" in html

    def test_evidence_keeps_reference_and_explicit_unresolved_status(self):
        out = self.svc.adjudicate_event("EXC-112394")
        doc = self.svc.evidence.get(out["bundle"]["bundle_id"], tenant_code=out["result"].tenant_code)
        assert doc["recommendation"]["disposition"] == CANDIDATE
        assert doc["recommendation"]["closure_eligibility"] == "historical_candidate_unverified"
        assert doc["recommendation"]["requires_human_review"] is True
        assert doc["inputs"]["alert"]["historical_classification"] == out["result"].historical_classification
        assert doc["inputs"]["resolution"]["closure_assessment"]["independent_closure_evidence"] == []
        assert self.svc.replay_from_bundle(doc["bundle_id"], out["result"].tenant_code)["identical"]

    def test_metrics_and_run_all_never_fold_candidates_into_closures(self):
        client = self.client()
        for route in ["/ops/health-report", "/ops/agreement", "/events"]:
            body = client.get(route).json()
            assert body["closure_counts"]["verified_auto_close"] == 0
            assert body["closure_counts"]["historical_candidates_unverified"] == 37
            assert body["closure_counts"]["other_auto_close_unverified"] == 0
        summary = self.svc.adjudicate_all(persist=False)
        assert summary["closure_counts"]["verified_auto_close"] == 0
        assert summary["closure_counts"]["historical_candidates_unverified"] == 37
        assert all(r["recommendation"] != AUTO_CLOSE for r in summary["rows"])
        assert all(r["requires_human_review"] for r in summary["rows"])

    def test_cli_outputs_explicit_candidate_fields_and_separate_counts(self):
        import sys

        root = Path(self._tmpdir.name) / "cli"
        base = [
            sys.executable,
            "-m",
            "kestrel",
            "--log-level",
            "WARNING",
            "--db",
            str(root / "test.sqlite"),
            "--evidence-dir",
            str(root / "evidence"),
        ]
        one = json.loads(
            subprocess.check_output(base + ["adjudicate", "--event", "EXC-112394", "--no-persist"], text=True)
        )
        assert one["recommendation"] == CANDIDATE
        assert one["requires_human_review"] is True
        assert one["closure_eligibility"] == "historical_candidate_unverified"
        batch = json.loads(
            subprocess.check_output(base + ["run-all", "--no-persist", "--out", str(root / "results.csv")], text=True)
        )
        assert batch["closure_counts"]["verified_auto_close"] == 0
        assert batch["closure_counts"]["historical_candidates_unverified"] == 37
        assert batch["counts"].get(AUTO_CLOSE, 0) == 0
        assert batch["counts"][CANDIDATE] == 37

    def test_candidate_cannot_be_signed_or_auto_closed_as_if_verified(self):
        from kestrel.domain import CaseState, Disposition, TransitionError

        out = self.svc.adjudicate_event("EXC-112394")
        with pytest.raises(TransitionError):
            self.svc.lifecycle.transition(out["case"]["case_id"], CaseState.CLOSED_AUTO)
        self.svc.lifecycle.transition(out["case"]["case_id"], CaseState.RECOMMENDED)
        with pytest.raises(TransitionError):
            self.svc.lifecycle.transition(out["case"]["case_id"], CaseState.CLOSED_AUTO)
        # Even moving to review cannot turn a review category into a final fate.
        self.svc.lifecycle.transition(out["case"]["case_id"], CaseState.AWAITING_REVIEWER)
        with pytest.raises(TransitionError):
            self.svc.lifecycle.sign(
                out["case"]["case_id"], "Reviewer", Disposition(CANDIDATE), bundle_hash=out["bundle"]["content_hash"]
            )


@pytest.mark.parametrize(
    "triage,event",
    [
        ("Sensor artefact", {"gateway_gap_min": 45, "interpolated": "Y"}),
        ("dock door", {"dock_door_open_flag": "N"}),
        ("Sensor artifact", {}),
    ],
)
def test_historical_guard_blocks_later_numeric_autoclose(triage, event):
    verdict, trace = decide(make_facts(event={"triage_outcome": triage, **event}, corrected_max_c=7))
    assert verdict.disposition == CANDIDATE
    assert "Decision rule: rule_historical_closure_guard" in trace


def test_numeric_rule_support_is_not_counted_as_independent_verification():
    from kestrel.closure import closure_counts

    assert closure_counts(
        [
            {"recommendation": AUTO_CLOSE, "closure_eligibility": "rule_supported_unverified"},
            {"recommendation": CANDIDATE, "closure_eligibility": "historical_candidate_unverified"},
        ]
    ) == {"verified_auto_close": 0, "historical_candidates_unverified": 1, "other_auto_close_unverified": 1}
