"""Product / GTIN / carrier-contract resolution with confidence scores."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from kestrel.ingest import DataPack

"""Resolve messy product / facility / carrier strings to canonical entities."""


@dataclass
class ResolvedProduct:
    """Product identity resolution result with match method, confidence, and stability study ref."""

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


def _norm(value: Any) -> str:
    """Normalize free text for fuzzy matching (lowercase, collapse whitespace)."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _presentation_from_text(text: str) -> Optional[str]:
    """Infer presentation (pen/vial/etc.) from brand or study text, if possible."""
    normalized = _norm(text)
    if "pre-filled" in normalized or "pfs" in normalized or "syringe" in normalized:
        return "pfs"
    if "pen" in normalized or "solojet" in normalized:
        return "pen"
    if "vial" in normalized:
        return "vial"
    if "tabs" in normalized or "tablet" in normalized or "sachet" in normalized:
        return "oral"
    return None


class IdentityResolver:
    """Map product_ref_as_received (+ tenant) onto 02_Product_Master rows.

    Uses GTIN / SKU / brand / INN exact match, then alias observations for
    PRODUCT kind, then fuzzy brand containment. Never invents a product.
    """

    def __init__(self, pack: DataPack) -> None:
        """Bind the resolver to a loaded DataPack."""
        self.pack = pack
        self._alias_pairs: dict[str, set[str]] = {}
        for alias in pack.aliases:
            if str(alias.get("entity_kind") or "").upper() != "PRODUCT":
                continue
            if str(alias.get("same_real_world_thing") or "").upper() != "Y":
                continue
            alias_a, alias_b = _norm(alias.get("string_a")), _norm(alias.get("string_b"))
            if not alias_a or not alias_b:
                continue
            self._alias_pairs.setdefault(alias_a, set()).add(alias_b)
            self._alias_pairs.setdefault(alias_b, set()).add(alias_a)

    def _product_strings(self, product: dict[str, Any]) -> set[str]:
        """Collect normalized identity strings from a product-master row."""
        keys = []
        for field_name in ("brand_as_labelled", "generic_inn", "internal_sku", "gtin", "legacy_code"):
            field_value = product.get(field_name)
            if field_value:
                keys.append(_norm(field_value))
        return set(keys)

    def resolve_product(self, tenant_code: str, product_ref: Any) -> ResolvedProduct:
        """Resolve a product_ref string to a canonical product for the tenant."""
        ref = (product_ref or "").strip() if product_ref else ""
        if not ref:
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="unresolved",
                confidence=0.0,
                unresolved_reason="blank product_ref_as_received",
            )

        ref_n = _norm(ref)
        tenant_products = [product for product in self.pack.products if product.get("tenant_code") == tenant_code]
        pool = tenant_products or list(self.pack.products)

        # 1. Exact GTIN
        for product in pool:
            if product.get("gtin") and _norm(product.get("gtin")) == ref_n:
                return self._from_row(product, "gtin_exact", 0.98)

        # 2. Exact SKU
        for product in pool:
            if product.get("internal_sku") and _norm(product.get("internal_sku")) == ref_n:
                return self._from_row(product, "sku_exact", 0.95)

        # 3. Exact brand / INN
        for product in pool:
            for field_name, conf in (("brand_as_labelled", 0.9), ("generic_inn", 0.85)):
                if product.get(field_name) and _norm(product.get(field_name)) == ref_n:
                    return self._from_row(product, f"{field_name}_exact", conf)

        # 4. Alias expansion then re-match
        expanded = {ref_n} | self._alias_pairs.get(ref_n, set())
        for alias in list(expanded):
            expanded |= self._alias_pairs.get(alias, set())
        for product in pool:
            strings = self._product_strings(product)
            if strings & expanded:
                return self._from_row(product, "alias_chain", 0.8)

        # 5. Brand containment (e.g. "Glucodyne 100U" vs "Glucodyne SoloJet 100U")
        hits = []
        for product in pool:
            brand = _norm(product.get("brand_as_labelled"))
            if brand and (brand in ref_n or ref_n in brand):
                hits.append(product)
            elif product.get("generic_inn") and _norm(product.get("generic_inn")) in ref_n:
                hits.append(product)
        if len(hits) == 1:
            return self._from_row(hits[0], "brand_containment", 0.7)
        if len(hits) > 1:
            # Prefer rows whose presentation matches ref
            hint = _presentation_from_text(ref)
            if hint:
                narrowed = [
                    hit
                    for hit in hits
                    if _presentation_from_text(
                        " ".join(str(hit.get(k) or "") for k in ("brand_as_labelled", "generic_inn", "internal_sku"))
                    )
                    == hint
                    or hint in _norm(hit.get("brand_as_labelled"))
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

    def _from_row(self, product: dict[str, Any], method: str, confidence: float) -> ResolvedProduct:
        """Build a ResolvedProduct from a product-master row and match metadata."""
        brand = product.get("brand_as_labelled")
        return ResolvedProduct(
            tenant_code=product.get("tenant_code") or "",
            match_method=method,
            confidence=confidence,
            brand=brand,
            generic_inn=product.get("generic_inn"),
            internal_sku=product.get("internal_sku"),
            gtin=str(product.get("gtin")) if product.get("gtin") else None,
            storage_spec_text=product.get("storage_spec_text"),
            permitted_excursion_text=product.get("permitted_excursion_text"),
            stability_study_ref=product.get("stability_study_ref"),
            light_sensitive=product.get("light_sensitive"),
            presentation_hint=_presentation_from_text(str(brand or "")),
            candidates=[product],
        )

    def resolve_facility_canonical(self, ref: Any) -> Optional[str]:
        """Return a preferred facility code if aliases map the string."""
        if not ref:
            return None
        ref_n = _norm(ref)
        # Prefer code_in_source exact
        for facility in self.pack.facilities:
            if _norm(facility.get("code_in_source")) == ref_n or _norm(facility.get("name_in_source")) == ref_n:
                return str(facility.get("code_in_source"))
        for alias in self.pack.aliases:
            if str(alias.get("entity_kind") or "").upper() != "FACILITY":
                continue
            if str(alias.get("same_real_world_thing") or "").upper() != "Y":
                continue
            if _norm(alias.get("string_a")) == ref_n:
                return str(alias.get("string_a"))
            if _norm(alias.get("string_b")) == ref_n:
                return str(alias.get("string_a"))
        return str(ref)

    def resolve_carrier_contract(
        self, carrier_ref: Any, as_of: Optional[date] = None
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Resolve a carrier alias to the contract row in force on as_of."""
        from datetime import date as date_cls

        as_of = as_of or date_cls.today()
        if not carrier_ref:
            return None, "blank carrier_ref"
        ref_n = _norm(carrier_ref)
        matches = []
        for contract in self.pack.carriers:
            names = [name.strip() for name in str(contract.get("names_seen_on_documents") or "").split("|")]
            name_norms = {_norm(name) for name in names if name}
            legal = _norm(contract.get("counterparty_legal_entity"))
            if (
                ref_n == legal
                or ref_n in name_norms
                or any(ref_n in name or name in ref_n for name in name_norms if name)
            ):
                effective_from, effective_to = contract.get("_effective_from"), contract.get("_effective_to")
                if effective_from and as_of < effective_from:
                    continue
                if effective_to and as_of > effective_to:
                    continue
                matches.append(contract)
        if not matches:
            return None, f"no contract for carrier {carrier_ref!r} as of {as_of}"
        if len(matches) > 1:
            # Prefer longest name overlap / more specific legal entity
            matches.sort(key=lambda contract: len(str(contract.get("counterparty_legal_entity") or "")), reverse=True)
        return matches[0], None
