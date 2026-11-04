"""Resolve messy product / facility / carrier strings to canonical entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from kestrel_sentinel.ingest.pack_memory import DataPack


@dataclass
class ResolvedProduct:
    tenant_code: str
    match_method: str
    confidence: float
    brand: Optional[str] = None
    generic_inn: Optional[str] = None
    internal_sku: Optional[str] = None
    gtin: Optional[str] = None
    storage_spec_text: Optional[str] = None
    permitted_excursion_text: Optional[str] = None
    stability_study_ref: Optional[str] = None
    light_sensitive: Optional[str] = None
    presentation_hint: Optional[str] = None  # pen / vial / pfs when guessable
    candidates: list[dict[str, Any]] = field(default_factory=list)
    unresolved_reason: Optional[str] = None


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().lower().replace("_", " ").split())


def _presentation_from_text(text: str) -> Optional[str]:
    t = _norm(text)
    if "pre-filled" in t or "pfs" in t or "syringe" in t:
        return "pfs"
    if "pen" in t or "solojet" in t:
        return "pen"
    if "vial" in t:
        return "vial"
    if "tabs" in t or "tablet" in t or "sachet" in t:
        return "oral"
    return None


class IdentityResolver:
    """Map product_ref_as_received (+ tenant) onto 02_Product_Master rows.

    Uses GTIN / SKU / brand / INN exact match, then alias observations for
    PRODUCT kind, then fuzzy brand containment. Never invents a product.
    """

    def __init__(self, pack: DataPack):
        self.pack = pack
        self._alias_pairs: dict[str, set[str]] = {}
        for a in pack.aliases:
            if str(a.get("entity_kind") or "").upper() != "PRODUCT":
                continue
            if str(a.get("same_real_world_thing") or "").upper() != "Y":
                continue
            sa, sb = _norm(a.get("string_a")), _norm(a.get("string_b"))
            if not sa or not sb:
                continue
            self._alias_pairs.setdefault(sa, set()).add(sb)
            self._alias_pairs.setdefault(sb, set()).add(sa)

    def _product_strings(self, p: dict[str, Any]) -> set[str]:
        keys = []
        for k in ("brand_as_labelled", "generic_inn", "internal_sku", "gtin", "legacy_code"):
            v = p.get(k)
            if v:
                keys.append(_norm(v))
        return set(keys)

    def resolve_product(self, tenant_code: str, product_ref: Any) -> ResolvedProduct:
        ref = (product_ref or "").strip() if product_ref else ""
        if not ref:
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="unresolved",
                confidence=0.0,
                unresolved_reason="blank product_ref_as_received",
            )

        ref_n = _norm(ref)
        tenant_products = [p for p in self.pack.products if p.get("tenant_code") == tenant_code]
        pool = tenant_products or list(self.pack.products)

        # 1. Exact GTIN
        for p in pool:
            if p.get("gtin") and _norm(p.get("gtin")) == ref_n:
                return self._from_row(p, "gtin_exact", 0.98)

        # 2. Exact SKU
        for p in pool:
            if p.get("internal_sku") and _norm(p.get("internal_sku")) == ref_n:
                return self._from_row(p, "sku_exact", 0.95)

        # 3. Exact brand / INN
        for p in pool:
            for field_name, conf in (("brand_as_labelled", 0.9), ("generic_inn", 0.85)):
                if p.get(field_name) and _norm(p.get(field_name)) == ref_n:
                    return self._from_row(p, f"{field_name}_exact", conf)

        # 4. Alias expansion then re-match
        expanded = {ref_n} | self._alias_pairs.get(ref_n, set())
        for alias in list(expanded):
            expanded |= self._alias_pairs.get(alias, set())
        for p in pool:
            strings = self._product_strings(p)
            if strings & expanded:
                return self._from_row(p, "alias_chain", 0.8)

        # 5. Brand containment (e.g. "Glucodyne 100U" vs "Glucodyne SoloJet 100U")
        hits = []
        for p in pool:
            brand = _norm(p.get("brand_as_labelled"))
            if brand and (brand in ref_n or ref_n in brand):
                hits.append(p)
            elif p.get("generic_inn") and _norm(p.get("generic_inn")) in ref_n:
                hits.append(p)
        if len(hits) == 1:
            return self._from_row(hits[0], "brand_containment", 0.7)
        if len(hits) > 1:
            # Prefer rows whose presentation matches ref
            hint = _presentation_from_text(ref)
            if hint:
                narrowed = [
                    h
                    for h in hits
                    if _presentation_from_text(
                        " ".join(
                            str(h.get(k) or "")
                            for k in ("brand_as_labelled", "generic_inn", "internal_sku")
                        )
                    )
                    == hint
                    or hint in _norm(h.get("brand_as_labelled"))
                ]
                if len(narrowed) == 1:
                    return self._from_row(narrowed[0], "brand_containment_presentation", 0.75)
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="ambiguous",
                confidence=0.4,
                candidates=hits[:5],
                unresolved_reason=f"ambiguous product match for {ref!r}: {len(hits)} candidates",
                presentation_hint=_presentation_from_text(ref),
            )

        return ResolvedProduct(
            tenant_code=tenant_code,
            match_method="unresolved",
            confidence=0.0,
            unresolved_reason=f"no product master match for {ref!r} under {tenant_code}",
            presentation_hint=_presentation_from_text(ref),
        )

    def _from_row(self, p: dict[str, Any], method: str, confidence: float) -> ResolvedProduct:
        brand = p.get("brand_as_labelled")
        return ResolvedProduct(
            tenant_code=p.get("tenant_code") or "",
            match_method=method,
            confidence=confidence,
            brand=brand,
            generic_inn=p.get("generic_inn"),
            internal_sku=p.get("internal_sku"),
            gtin=str(p.get("gtin")) if p.get("gtin") else None,
            storage_spec_text=p.get("storage_spec_text"),
            permitted_excursion_text=p.get("permitted_excursion_text"),
            stability_study_ref=p.get("stability_study_ref"),
            light_sensitive=p.get("light_sensitive"),
            presentation_hint=_presentation_from_text(str(brand or "")),
            candidates=[p],
        )

    def resolve_facility_canonical(self, ref: Any) -> Optional[str]:
        """Return a preferred facility code if aliases map the string."""
        if not ref:
            return None
        ref_n = _norm(ref)
        # Prefer code_in_source exact
        for f in self.pack.facilities:
            if _norm(f.get("code_in_source")) == ref_n or _norm(f.get("name_in_source")) == ref_n:
                return str(f.get("code_in_source"))
        for a in self.pack.aliases:
            if str(a.get("entity_kind") or "").upper() != "FACILITY":
                continue
            if str(a.get("same_real_world_thing") or "").upper() != "Y":
                continue
            if _norm(a.get("string_a")) == ref_n:
                return str(a.get("string_a"))
            if _norm(a.get("string_b")) == ref_n:
                return str(a.get("string_a"))
        return str(ref)

    def resolve_carrier_contract(self, carrier_ref: Any, as_of: Optional[date] = None):
        from datetime import date as date_cls

        as_of = as_of or date_cls.today()
        if not carrier_ref:
            return None, "blank carrier_ref"
        ref_n = _norm(carrier_ref)
        matches = []
        for c in self.pack.carriers:
            names = [n.strip() for n in str(c.get("names_seen_on_documents") or "").split("|")]
            name_norms = {_norm(n) for n in names if n}
            legal = _norm(c.get("counterparty_legal_entity"))
            if ref_n == legal or ref_n in name_norms or any(ref_n in n or n in ref_n for n in name_norms if n):
                ef, et = c.get("_effective_from"), c.get("_effective_to")
                if ef and as_of < ef:
                    continue
                if et and as_of > et:
                    continue
                matches.append(c)
        if not matches:
            return None, f"no contract for carrier {carrier_ref!r} as of {as_of}"
        if len(matches) > 1:
            # Prefer longest name overlap / more specific legal entity
            matches.sort(key=lambda c: len(str(c.get("counterparty_legal_entity") or "")), reverse=True)
        return matches[0], None


# late import type
from datetime import date  # noqa: E402
