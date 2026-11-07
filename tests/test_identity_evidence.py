"""Typed identity provenance, negative links and scoped resolution contracts."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kestrel.api.app import create_app
from kestrel.config import _DEFAULT_PACK
from kestrel.domain import Disposition
from kestrel.engine import AdjudicationEngine
from kestrel.ingest import DataPack
from kestrel.lifecycle import TransitionError
from kestrel.rules.identity import IdentityResolver
from tests._base import _make_tmp_svc


@pytest.fixture(scope="module")
def real_pack():
    return DataPack.load(_DEFAULT_PACK)


def product(**patch):
    return dict(
        tenant_code="T-A",
        gtin="001234",
        internal_sku="SKU-A",
        brand_as_labelled="Drug 40mg PFS",
        storage_spec_text="2-8 C",
        _source_sheet="02_Product_Master",
        _source_row=2,
        **patch,
    )


def alias(a="old", b="Drug 40mg PFS", **patch):
    row = dict(
        entity_kind="PRODUCT",
        tenant_code="T-A",
        string_a=a,
        string_b=b,
        same_real_world_thing="Y",
        confirmed_by="QA-A",
        confirmed_on="2025-01-01",
        _source_sheet="07_Alias_Observations",
        _source_row=2,
    )
    row.update(patch)
    return row


def pack(products=None, aliases=None, facilities=None, carriers=None):
    return DataPack(
        path=Path("synthetic"),
        products=products or [],
        aliases=aliases or [],
        facilities=facilities or [],
        carriers=carriers or [],
    )


@pytest.mark.parametrize(
    "comment", ["Strength differs — check before merging", "Same molecule, different presentation"]
)
def test_negative_alias_comments_block_merge(comment):
    p = IdentityResolver(pack([product()], [alias(comment=comment)])).resolve_product("T-A", "old")
    assert p.internal_sku is None
    assert not p.release_identity_eligible
    assert p.status == "UNRESOLVED_CONFLICT"
    assert any(link.conflict_note == comment for link in p.identity_links)


@pytest.mark.parametrize("row_number", [84, 86])
def test_real_negative_alias_rows(real_pack, row_number):
    raw = real_pack.aliases[row_number - 2]
    resolver = IdentityResolver(real_pack)
    p = resolver.resolve_product("T-VIRENT", raw["string_a"])
    assert not p.release_identity_eligible
    assert p.status.startswith("UNRESOLVED")
    assert any(link.source_row == row_number and link.conflict_note for link in p.identity_links)


@pytest.mark.parametrize("bridge", ["Drug 20mg PFS", "Drug 40mg vial"])
def test_multihop_never_crosses_strength_or_presentation(bridge):
    resolver = IdentityResolver(pack([product()], [alias("old", bridge), alias(bridge, "Drug 40mg PFS")]))
    p = resolver.resolve_product("T-A", "old")
    assert p.internal_sku is None
    assert p.status == "UNRESOLVED_CONFLICT"
    assert any("MISMATCH" in reason for reason in p.reasons)


@pytest.mark.parametrize("change", ["unconfirmed", "unowned", "negative", "foreign", "conflicting-alternate"])
def test_weak_or_foreign_alias_never_authorizes_release(change):
    a = alias()
    aliases = [a]
    if change == "unconfirmed":
        a["confirmed_by"] = None
    if change == "unowned":
        a.pop("tenant_code")
    if change == "negative":
        a["same_real_world_thing"] = "N"
    if change == "foreign":
        a["tenant_code"] = "T-B"
    if change == "conflicting-alternate":
        aliases = [
            alias("old", "middle"),
            alias("middle", "Drug 40mg PFS"),
            alias("old", "Drug 40mg PFS", same_real_world_thing="N"),
        ]
    p = IdentityResolver(pack([product()], aliases)).resolve_product("T-A", "old", as_of=date(2026, 1, 1))
    assert p.internal_sku is None
    assert not p.release_identity_eligible
    assert p.status.startswith("UNRESOLVED")
    assert p.reasons


def test_scoped_confirmed_alias_retains_every_hop():
    p = IdentityResolver(
        pack([product()], [alias("old", "middle"), alias("middle", "Drug 40mg PFS", _source_row=3)])
    ).resolve_product("T-A", "old", as_of=date(2026, 1, 1))
    assert p.release_identity_eligible
    links = [asdict(link) for link in p.identity_links]
    assert {link["source_row"] for link in links if link["kind"] == "ALIAS"} == {2, 3}
    assert all(link["tenant_code"] == "T-A" for link in links)
    assert all(link["verification_status"] == "CONFIRMED_SOURCE_ASSERTION" for link in links if link["kind"] == "ALIAS")


def test_future_confirmation_is_not_current_identity():
    p = IdentityResolver(pack([product()], [alias(confirmed_on="2027-01-01")])).resolve_product(
        "T-A", "old", as_of=date(2026, 1, 1)
    )
    assert not p.release_identity_eligible
    assert "CONFIRMATION_NOT_IN_FORCE" in p.reasons


@pytest.mark.parametrize("kind,ref", [("EXACT_GTIN", "001234"), ("EXACT_SKU", "SKU-A")])
def test_exact_links_have_tenant_and_real_source(kind, ref):
    p = IdentityResolver(pack([product()])).resolve_product("T-A", ref)
    assert p.release_identity_eligible
    link = asdict(p.identity_links[0])
    assert link["kind"] == kind and link["tenant_code"] == "T-A"
    assert link["source_sheet"] == "02_Product_Master" and link["source_row"] == 2
    assert link["verification_status"] == "SOURCE_ASSERTED"
    assert link["confirmed_by"] is None and link["confirmed_on"] is None


def test_duplicate_gtin_is_explicit_ambiguity():
    a = product()
    b = {**a, "internal_sku": "SKU-B", "_source_row": 3}
    p = IdentityResolver(pack([a, b])).resolve_product("T-A", "001234")
    assert not p.release_identity_eligible and p.status == "UNRESOLVED_AMBIGUOUS"
    assert len(p.candidates) == 2 and len(p.identity_links) == 2


def test_cross_tenant_master_is_never_used():
    p = IdentityResolver(pack([product()])).resolve_product("T-B", "001234")
    assert p.status == "UNRESOLVED" and not p.candidates and not p.identity_links


@pytest.mark.parametrize("carrier_ref,expected", [("AFX-DE", "CNT-2023-0441"), ("Tapti Exp Cargo", "CNT-2021-0245")])
def test_carrier_contract_scoped_provenance(real_pack, carrier_ref, expected):
    resolver = IdentityResolver(real_pack)
    row, err = resolver.resolve_carrier_contract(carrier_ref, date(2026, 7, 28))
    assert err is None
    result = resolver.resolve_carrier("T-KAVERI", carrier_ref, date(2026, 7, 28))
    assert result.record["contract_id"] == row["contract_id"]
    assert row["contract_id"] == expected
    assert result.links and all(link.contract_id == row["contract_id"] for link in result.links)
    assert all(
        link.tenant_code == "T-KAVERI" and link.source_sheet == "04_Carrier_Contracts" and link.source_row
        for link in result.links
    )


def test_carrier_ambiguity_and_foreign_scope(real_pack):
    p = copy.deepcopy(real_pack)
    for c in p.carriers[:2]:
        c["names_seen_on_documents"] = "SAME"
    r = IdentityResolver(p).resolve_carrier("T-KAVERI", "SAME", date(2026, 7, 28))
    assert r.status == "UNRESOLVED_AMBIGUOUS" and not r.record and r.reasons
    for c in p.carriers:
        c["tenant_code"] = "T-OTHER"
    r = IdentityResolver(p).resolve_carrier("T-KAVERI", "AFX-DE", date(2026, 7, 28))
    assert r.status == "UNRESOLVED" and not r.record


def test_facility_duplicate_name_is_not_first_hit():
    rows = [
        dict(
            tenant_code="T-A",
            name_in_source="Cold store",
            code_in_source=c,
            _source_sheet="03_Facility_Registry",
            _source_row=i,
        )
        for i, c in [(2, "A"), (3, "B")]
    ]
    resolver = IdentityResolver(pack(facilities=rows))
    result = resolver.resolve_facility("T-A", "Cold store")
    assert result.status == "UNRESOLVED_AMBIGUOUS" and not result.record
    assert all(link.kind == "FACILITY" for link in result.links)
    assert resolver.resolve_facility_canonical("Cold store", tenant_code="T-A") is None


def test_unowned_facility_is_explicitly_unused(real_pack):
    r = AdjudicationEngine(real_pack).adjudicate(real_pack.event_by_id("EXC-107133"))
    f = r.identity_evidence["facility"]
    assert f["usage"] == "UNUSED_NOT_AUTHORITY_INPUT" and f["status"].startswith("UNRESOLVED")
    assert f["reasons"]


def test_all_previous_alias_chain_events_are_candidates_only(real_pack):
    # Frozen before implementation, not recomputed using the new resolver.
    ids = json.loads((Path(__file__).parent / "identity_alias_cases.json").read_text())
    resolver = IdentityResolver(real_pack)
    assert len(ids) == 81 and "EXC-112289" in ids
    for event_id in ids:
        e = real_pack.event_by_id(event_id)
        p = resolver.resolve_product(e["tenant_code"], e["product_ref_as_received"])
        assert p.status.startswith("UNRESOLVED"), event_id
        assert not p.release_identity_eligible and p.internal_sku is None, event_id
        assert p.reasons and p.identity_links, event_id


def test_source_row_numbers_survive_blank_rows():
    from openpyxl import Workbook

    from kestrel.utils import sheet_rows

    w = Workbook()
    s = w.active
    s.title = "Test"
    s.append(["id"])
    s.append([1])
    s.append([None])
    s.append([2])
    rows = sheet_rows(s, include_source=True)
    assert [(r["_source_sheet"], r["_source_row"]) for r in rows] == [("Test", 2), ("Test", 4)]


@pytest.fixture
def service(tmp_path):
    return _make_tmp_svc(tmp_path)


def test_api_and_sealed_evidence_show_unresolved_identity(service):
    client = TestClient(create_app(service))
    response = client.post("/adjudicate", json={"event_id": "EXC-112289", "persist": True})
    assert response.status_code == 200
    data = response.json()
    p = data["identity_evidence"]["product"]
    assert p["status"].startswith("UNRESOLVED") and p["reasons"] and p["links"]
    doc = client.get(f"/evidence/{data['bundle_id']}", params={"tenant_code": "T-CAMPOS"}).json()
    assert doc["inputs"]["resolution"]["identity"] == data["identity_evidence"]
    detail = client.get("/events/EXC-112289").json()
    assert detail["identity_evidence"] == data["identity_evidence"]
    schema = json.dumps(client.get("/openapi.json").json())
    for key in [
        "identity_evidence",
        "verification_status",
        "source_sheet",
        "source_row",
        "confirmed_by",
        "confirmed_on",
        "conflict_note",
    ]:
        assert key in schema


def test_release_signing_cannot_promote_unverified_alias(service):
    out = service.adjudicate_event("EXC-112289", persist=True)
    with pytest.raises(TransitionError, match="identity unresolved"):
        service.lifecycle.sign(
            out["case"]["case_id"], "QA", Disposition.RELEASE_WITH_NOTE, bundle_hash=out["bundle"]["content_hash"]
        )


def test_ui_renders_identity_status_and_escapes_source_notes(service):
    html = TestClient(create_app(service)).get("/ui").text
    assert "function identityPanel" in html and "identityPanel(data.identity_evidence)" in html
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable; static UI assertion passed")
    esc = re.search(r"const esc = .*", html).group(0)
    function = html.split("// BEGIN IDENTITY PANEL")[1].split("// END IDENTITY PANEL")[0]
    payload = {
        "product": {
            "status": "UNRESOLVED_CONFLICT",
            "reasons": ["Strength differs"],
            "links": [
                {
                    "kind": "ALIAS",
                    "verification_status": "CONFLICT",
                    "source_sheet": "07_Alias_Observations",
                    "source_row": 84,
                    "tenant_code": "T-A",
                    "confirmed_by": None,
                    "confirmed_on": None,
                    "conflict_note": "<script>bad</script>",
                }
            ],
        }
    }
    script = esc + "\n" + function + "\nconsole.log(identityPanel(" + json.dumps(payload) + "));"
    rendered = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True).stdout
    assert "UNRESOLVED_CONFLICT" in rendered and "Strength differs" in rendered and "84" in rendered
    assert "&lt;script&gt;" in rendered and "<script>bad" not in rendered


def test_unverified_identity_blocks_even_an_earlier_release(real_pack, monkeypatch):
    engine = AdjudicationEngine(real_pack)
    monkeypatch.setattr(
        engine,
        "_decide",
        lambda **kwargs: ("RELEASE_WITH_NOTE", "synthetic", 1.0, ["Decision rule: synthetic_release"]),
    )
    result = engine.adjudicate(real_pack.event_by_id("EXC-112289"))
    assert result.recommendation == "ESCALATED_TO_SENIOR_QA"
    assert result.evidence["decision"]["rule"] == "typed_identity_release_gate"


@pytest.mark.parametrize("bridge", ["Drug 40mcg PFS", "Drug 4g PFS", "Drug 40mg/mL PFS"])
def test_incompatible_strength_units_cannot_be_merged(bridge):
    p = IdentityResolver(pack([product()], [alias("old", bridge), alias(bridge, "Drug 40mg PFS")])).resolve_product(
        "T-A", "old", as_of=date(2026, 1, 1)
    )
    assert p.status == "UNRESOLVED_CONFLICT"
    assert not p.release_identity_eligible


def test_historical_text_cannot_hide_unresolved_product_identity(real_pack):
    event = real_pack.event_by_id("EXC-111988")
    result = AdjudicationEngine(real_pack).adjudicate(event)
    assert result.recommendation == "ESCALATED_TO_SENIOR_QA"
    assert result.evidence["decision"]["rule"] == "typed_identity_unresolved_gate"
    assert result.historical_classification == event["triage_outcome"]


def test_owned_negative_claim_conflicting_with_exact_master_key_blocks_identity():
    resolver = IdentityResolver(pack([product()], [alias("001234", "Drug 40mg PFS", same_real_world_thing="N")]))
    result = resolver.resolve_product("T-A", "001234")
    assert result.status == "UNRESOLVED_CONFLICT"
    assert not result.release_identity_eligible and result.internal_sku is None
    assert "NEGATIVE_RELATIONSHIP" in result.reasons


@pytest.mark.parametrize(
    "patch", [{"verification_status": "UNKNOWN"}, {"verification_status": "PENDING"}, {"confirmed_by": "   "}]
)
def test_unknown_verification_or_blank_confirmer_never_authorizes_alias(patch):
    resolver = IdentityResolver(pack([product()], [alias(**patch)]))
    result = resolver.resolve_product("T-A", "old", as_of=date(2026, 1, 1))
    assert not result.release_identity_eligible
    assert result.internal_sku is None
    assert "UNCONFIRMED_ALIAS" in result.reasons
