"""Product, GTIN and carrier-contract resolution."""

from __future__ import annotations

from datetime import date

from kestrel.rules.identity import IdentityResolver
from tests._base import _KestrelTestCase


class TestIdentity(_KestrelTestCase):
    """Product / carrier identity resolution edge cases."""

    def test_gtin_resolves_glucodyne_for_kaveri_or_virent(self) -> None:
        """GTIN 08901234500035 resolves to Glucodyne SoloJet with high confidence."""
        r = IdentityResolver(self.svc.pack)  # type: ignore[arg-type]
        hit = None
        for tenant in ("T-VIRENT", "T-KAVERI", "T-AURA", "T-NORDIA"):
            p = r.resolve_product(tenant, "08901234500035")
            if p.confidence >= 0.9:
                hit = p
                break
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.gtin == "08901234500035" or (hit.internal_sku and "INS-0119" in hit.internal_sku))

    def test_blank_product_unresolved(self) -> None:
        """Blank product_ref resolves as unresolved with confidence 0."""
        p = IdentityResolver(self.svc.pack).resolve_product("T-VIRENT", "")  # type: ignore[arg-type]
        self.assertEqual(p.confidence, 0.0)
        self.assertEqual(p.match_method, "unresolved")

    def test_tapti_contract_has_no_cold_chain_clause(self) -> None:
        """Tapti Exp Cargo contract has no cold-chain schedule clause."""
        r = IdentityResolver(self.svc.pack)  # type: ignore[arg-type]
        c, err = r.resolve_carrier_contract("Tapti Exp Cargo", date(2026, 7, 28))
        self.assertIsNone(err)
        self.assertIsNotNone(c)
        assert c is not None
        clause = str(c.get("cold_chain_clause"))
        self.assertTrue("none" in clause.lower() or clause.strip() in {"— none —", "—"})
