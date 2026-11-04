from adjudication.identity import IdentityResolver


def test_gtin_resolves_glucodyne_for_kaveri_or_virent(pack):
    """Brief EXC-107133 used GTIN 08901234500035 = Glucodyne SoloJet / SKU-INS-0119."""
    r = IdentityResolver(pack)
    # GTIN appears on T-VIRENT product master; event tenant is T-KAVERI which may not have row
    # Engine should still resolve via cross-tenant GTIN when tenant pool empty of match.
    hit = None
    for tenant in ("T-VIRENT", "T-KAVERI", "T-AURA", "T-NORDIA"):
        p = r.resolve_product(tenant, "08901234500035")
        if p.confidence >= 0.9:
            hit = p
            break
    assert hit is not None
    assert hit.gtin == "08901234500035" or (hit.internal_sku and "INS-0119" in hit.internal_sku)


def test_blank_product_unresolved(pack):
    p = IdentityResolver(pack).resolve_product("T-VIRENT", "")
    assert p.confidence == 0.0
    assert p.match_method == "unresolved"


def test_tapti_contract_has_no_cold_chain_clause(pack):
    r = IdentityResolver(pack)
    from datetime import date

    c, err = r.resolve_carrier_contract("Tapti Exp Cargo", date(2026, 7, 28))
    assert err is None
    assert c is not None
    assert "none" in str(c.get("cold_chain_clause")).lower() or str(c.get("cold_chain_clause")).strip() in {
        "— none —",
        "—",
    }
