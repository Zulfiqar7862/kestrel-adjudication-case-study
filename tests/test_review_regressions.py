"""Safety regressions found in reviewer fact-check; not clinical validation."""

import json
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from kestrel.domain import CaseState, Disposition, TransitionError
from kestrel.engine import AdjudicationEngine
from kestrel.exceptions import StaleEvidenceError
from kestrel.ingest import DataPack
from kestrel.rules.identity import IdentityResolver, ResolvedProduct
from kestrel.rules.stability import StabilityResolver, _parse_allowance
from kestrel.shadow import shadow_replay_bulletin
from tests._base import _KestrelTestCase


def fixture(min_c=3.0, max_c=8.0, firmware="TT-2.14.3"):
    pack = DataPack(
        path=Path("fixture"),
        products=[
            {
                "tenant_code": "T-X",
                "gtin": "123",
                "brand_as_labelled": "test vial",
                "storage_spec_text": "2-8 °C",
                "permitted_excursion_text": "No excursion permitted",
                "stability_study_ref": "S",
            }
        ],
    )
    event = {
        "event_id": "E",
        "tenant_code": "T-X",
        "product_ref_as_received": "123",
        "min_temp_c": min_c,
        "max_temp_c": max_c,
        "mean_temp_c": (min_c + max_c) / 2,
        "duration_min": 10,
        "logger_fw": firmware,
        "_alert_ts": datetime(2026, 1, 2),
    }
    # Synthetic contextual study only: no approval/effectivity/strength authority.
    # Item 4 must reject its use for a clinical fate, while preserving raw summaries.
    pack.stability = [
        {
            "tenant_code": "T-X",
            "study_ref": "S",
            "product_text_as_written": "test vial",
            "study_type": "Excursion / thermal cycling",
            "readable": "Y",
            "permitted_excursion_text": "No excursion permitted",
        }
    ]
    pack.events = [event]
    return pack, event


class TestTemperatureAndIdentity(unittest.TestCase):
    def test_bulletin_threshold_crossing_escalates_and_keeps_reported(self):
        p, event = fixture(max_c=8)
        before = deepcopy(event)
        r = AdjudicationEngine(p).adjudicate(event)
        self.assertEqual(r.recommendation, "ESCALATED_TO_SENIOR_QA")
        self.assertTrue(r.requires_human_signature)
        self.assertEqual(r.reported_max_temp_c, 8)
        u = r.evidence["temps"]["uncertainty"]
        self.assertEqual(u["reported_scenario"]["recommendation"], "AUTO_CLOSE")
        self.assertEqual(u["upper_bound_scenario"]["max_c"], 9.8)
        self.assertNotIn("max_corrected", r.evidence["temps"])
        self.assertEqual(event, before)

    def test_bulletin_freeze_lower_bound_is_not_silently_released(self):
        p, event = fixture(min_c=-0.1, max_c=6)
        r = AdjudicationEngine(p).adjudicate(event)
        u = r.evidence["temps"]["uncertainty"]
        # Item 4: an unapproved, undated index prohibition cannot establish DESTROY.
        # Conditional freeze arithmetic is still covered below the discovery gate.
        self.assertEqual(u["reported_scenario"]["recommendation"], "ESCALATED_TO_SENIOR_QA")
        self.assertEqual(u["upper_bound_scenario"]["recommendation"], "ESCALATED_TO_SENIOR_QA")
        self.assertEqual(r.evidence["temps"]["min_reported"], -0.1)
        self.assertEqual(u["upper_bound_scenario"]["max_c"], 7.8)
        self.assertIsNone(r.study_discovery["selected_study_ref"])
        self.assertIn("APPROVAL_UNKNOWN", str(r.study_discovery))
        self.assertEqual(r.recommendation, "ESCALATED_TO_SENIOR_QA")

    def test_bulletin_same_outcome_stays_flagged(self):
        p, event = fixture(max_c=20)
        r = AdjudicationEngine(p).adjudicate(event)
        # Missing study authority must not invent a destructive clinical fate.
        self.assertEqual(r.recommendation, "ESCALATED_TO_SENIOR_QA")
        self.assertIsNone(r.study_discovery["selected_study_ref"])
        self.assertIn("APPROVAL_UNKNOWN", str(r.study_discovery))
        self.assertEqual(r.reported_max_temp_c, 20)
        self.assertTrue(r.bulletin_applied)
        self.assertFalse(r.evidence["temps"]["uncertainty"]["outcome_sensitive"])

    def test_unaffected_firmware_has_no_shift(self):
        p, event = fixture(firmware="TT-2.15.0")
        r = AdjudicationEngine(p).adjudicate(event)
        self.assertEqual(r.reported_max_temp_c, 8)
        self.assertNotIn("uncertainty", r.evidence["temps"])
        self.assertEqual(r.recommendation, "AUTO_CLOSE")

    def test_qualified_prohibition_is_cap_not_unconditional_ban(self):
        a = _parse_allowance("No excursion above 25 °C permitted")
        self.assertFalse(a["no_excursion"])
        self.assertEqual(a["max_temp_c"], 25)
        self.assertTrue(a["qualified_cap"])
        self.assertIsNone(a["max_duration_hours"])

    def test_unqualified_prohibition_remains_ban(self):
        self.assertTrue(_parse_allowance("No excursion permitted")["no_excursion"])

    def test_qualified_cap_missing_duration_never_invents_release_or_destroy(self):
        for max_c in [10, 25, 25.1]:
            p, e = fixture(max_c=max_c, firmware="other")
            p.products[0]["permitted_excursion_text"] = "No excursion above 25 °C permitted"
            p.stability[0]["permitted_excursion_text"] = "No excursion above 25 °C permitted"
            r = AdjudicationEngine(p).adjudicate(e)
            self.assertEqual(r.recommendation, "ESCALATED_TO_SENIOR_QA")
            self.assertIn("no duration", " ".join(r.rationale))

    def test_unknown_tenant_fails_closed_even_for_historical_noise(self):
        p, e = fixture()
        e.update(tenant_code="T-UNKNOWN", triage_outcome="duplicate alert")
        self.assertEqual(IdentityResolver(p).resolve_product("T-UNKNOWN", "123").confidence, 0)
        self.assertEqual(AdjudicationEngine(p).adjudicate(e).recommendation, "ESCALATED_TO_SENIOR_QA")

    def test_duplicate_gtin_is_ambiguous_within_tenant(self):
        p, _ = fixture()
        p.products.append({**p.products[0], "brand_as_labelled": "other vial"})
        r = IdentityResolver(p).resolve_product("T-X", "123")
        self.assertEqual(r.match_method, "ambiguous")

    def test_same_gtin_in_another_tenant_does_not_leak(self):
        p, _ = fixture()
        p.products.insert(0, {**p.products[0], "tenant_code": "T-OTHER", "brand_as_labelled": "secret"})
        self.assertEqual(IdentityResolver(p).resolve_product("T-X", "123").brand, "test vial")

    def test_study_reference_is_tenant_scoped(self):
        p, _ = fixture()
        p.stability = [
            {"study_ref": "S", "tenant_code": "T-OTHER", "permitted_excursion_text": "No excursion permitted"}
        ]
        r = StabilityResolver(p).resolve(ResolvedProduct("T-X", "gtin_exact", 0.98, stability_study_ref="S"))
        self.assertEqual(r.source, "unresolved")
        self.assertIsNotNone(r.authority_issue)

    def test_shadow_custom_bound_drives_arithmetic(self):
        p, _ = fixture(max_c=7)
        low = shadow_replay_bulletin(p, AdjudicationEngine(p), bias_c=0.1)
        high = shadow_replay_bulletin(p, AdjudicationEngine(p), bias_c=1.8)
        self.assertEqual(low["disposition_flips"], 0)
        self.assertEqual(high["disposition_flips"], 1)


class TestSignedAndReplayedEvidence(_KestrelTestCase):
    def test_sign_requires_viewed_hash(self):
        out = self.svc.adjudicate_event("EXC-107133")
        for value in [None, "", "wrong"]:
            with self.assertRaises(StaleEvidenceError):
                self.svc.lifecycle.sign(out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=value)

    def test_sign_artifact_appears_in_basis_without_mutating_original(self):
        out = self.svc.adjudicate_event("EXC-107133")
        original = deepcopy(out["bundle"])
        signed = self.svc.lifecycle.sign(
            out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=original["content_hash"]
        )
        basis = self.svc.full_basis("EXC-107133", "T-KAVERI")["bundle"]
        self.assertEqual(basis["reviewer_signoff"]["status"], "SIGNED")
        self.assertEqual(basis["case_id"], signed["case_id"])
        self.assertEqual(basis["reviewer_signoff"]["signed_bundle_hash"], original["content_hash"])
        self.assertEqual(self.svc.evidence.get(original["bundle_id"], tenant_code="T-KAVERI"), original)
        self.assertTrue(self.svc.verify_tenant_chain("T-KAVERI")["ok"])

    def test_sign_rejects_tampered_bundle_even_with_matching_stored_hash(self):
        out = self.svc.adjudicate_event("EXC-107133")
        meta = self.svc.store.get_evidence_meta(out["bundle"]["bundle_id"], tenant_code="T-KAVERI")
        path = Path(meta["path"])
        original = path.read_text()
        doc = json.loads(original)
        doc["reasoning_steps"].append("tamper")
        path.write_text(json.dumps(doc))
        try:
            with self.assertRaises(StaleEvidenceError):
                self.svc.lifecycle.sign(
                    out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=doc["content_hash"]
                )
        finally:
            path.write_text(original)

    def test_generic_transition_cannot_bypass_signature(self):
        out = self.svc.adjudicate_event("EXC-107133")
        with self.assertRaises(TransitionError):
            self.svc.lifecycle.transition(out["case"]["case_id"], CaseState.CLOSED_SIGNED, signed_by="QA")

    def test_replay_uses_sealed_inputs_after_live_pack_removed(self):
        out = self.svc.adjudicate_event("EXC-107133")
        pack, engine = self.svc.pack, self.svc.engine
        self.svc.pack = self.svc.engine = None
        before = len(self.svc.store.chain_for_tenant("T-KAVERI"))
        try:
            for _ in range(2):
                self.assertTrue(self.svc.replay_from_bundle(out["bundle"]["bundle_id"], "T-KAVERI")["identical"])
        finally:
            self.svc.pack, self.svc.engine = pack, engine
        self.assertEqual(len(self.svc.store.chain_for_tenant("T-KAVERI")), before)

    def test_replay_compares_full_result_and_rejects_other_versions(self):
        out = self.svc.adjudicate_event("EXC-107133")
        self.assertIn("expected_result", out["bundle"]["inputs"])
        self.assertEqual(
            out["bundle"]["inputs"]["expected_result"]["recommendation"], asdict(out["result"])["recommendation"]
        )
        version = self.svc.settings.rule_pack_version
        self.svc.settings.rule_pack_version = "unavailable"
        try:
            with self.assertRaises(ValueError):
                self.svc.replay_from_bundle(out["bundle"]["bundle_id"], "T-KAVERI")
        finally:
            self.svc.settings.rule_pack_version = version

    def test_reopen_preserves_deadline_reportability_and_prior_signature(self):
        out = self.svc.adjudicate_event("EXC-107133")
        signed = self.svc.lifecycle.sign(
            out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=out["bundle"]["content_hash"]
        )
        reopened = self.svc.lifecycle.reopen(signed["case_id"], "bulletin review")
        self.assertEqual(reopened["reg_deadline_utc"], signed["reg_deadline_utc"])
        self.assertEqual(reopened["regulator_reportable"], signed["regulator_reportable"])
        prior = self.svc.store.get_case(signed["case_id"])
        self.assertEqual(prior["signed_by"], "QA")
        signature = self.svc.evidence.get(prior["signature_bundle_id"], tenant_code="T-KAVERI")
        self.assertEqual(signature["reviewer_signoff"]["status"], "SIGNED")
