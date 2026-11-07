"""Typed tenant/contract-scoped identity claims; candidates are not authority."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal, Optional

from kestrel.ingest import DataPack
from kestrel.utils import parse_date


@dataclass
class IdentityLink:
    """A source assertion, not independent verification or a cross-tenant edge."""

    kind: Literal["EXACT_GTIN", "EXACT_SKU", "ALIAS", "LEGAL_ENTITY", "FACILITY"]
    tenant_code: str
    source_sheet: Optional[str]
    source_row: Optional[int]
    verification_status: str
    confirmed_by: Optional[str] = None
    confirmed_on: Optional[str] = None
    conflict_note: Optional[str] = None
    source_tenant_code: Optional[str] = None
    contract_id: Optional[str] = None
    left: str = ""
    right: str = ""
    scope_basis: str = "tenant_master"


@dataclass
class IdentityResolution:
    status: str = "UNRESOLVED"
    reasons: list[str] = field(default_factory=list)
    links: list[IdentityLink] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    record: Optional[dict[str, Any]] = None
    release_identity_eligible: bool = False
    usage: str = "REFERENCE_IDENTITY_ONLY"

    def assessment(self) -> dict[str, Any]:
        return json.loads(json.dumps({k: v for k, v in asdict(self).items() if k != "record"}, default=str))


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
    presentation_hint: Optional[str] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    unresolved_reason: Optional[str] = None
    status: str = "UNRESOLVED"
    reasons: list[str] = field(default_factory=list)
    identity_links: list[IdentityLink] = field(default_factory=list)
    release_identity_eligible: bool = False

    def assessment(self) -> dict[str, Any]:
        return json.loads(
            json.dumps(
                {
                    "status": self.status,
                    "reasons": self.reasons,
                    "links": [asdict(link) for link in self.identity_links],
                    "candidates": self.candidates,
                    "release_identity_eligible": self.release_identity_eligible,
                    "usage": "PRODUCT_IDENTITY",
                    "match_method": self.match_method,
                },
                default=str,
            )
        )


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


def _note(row: dict[str, Any]) -> Optional[str]:
    return "; ".join(str(row[k]) for k in ("comment", "conflict_note", "negative_note") if row.get(k)) or None


def _dimension_conflicts(strings: set[str]) -> list[str]:
    """Reject explicit differences; never infer missing strength/presentation."""
    forms = {_presentation_from_text(s) for s in strings} - {None}
    reasons = ["PRESENTATION_MISMATCH"] if len(forms) > 1 else []
    signatures = set()
    for text in strings:
        values = re.findall(r"(\d+(?:\.\d+)?)\s*((?:mcg|mg|ng|g|iu|u)(?:\s*/\s*(?:ml|l))?)(?![a-z])", _norm(text))
        if values:
            signatures.add(frozenset((str(float(value)), unit.replace(" ", "")) for value, unit in values))
    if len(signatures) > 1:
        reasons.append("STRENGTH_OR_UNIT_MISMATCH")
    return reasons


class IdentityResolver:
    """Exact tenant master keys, or explicit owned and confirmed alias paths.

    Tenantless observations are displayed as candidates only. Legal entities use
    contract scope, never a parent-group/substring identity promotion. Facility
    resolution is deliberately unused by adjudication/SOP selection in this item.
    """

    def __init__(self, pack: DataPack) -> None:
        self.pack = pack

    def _product_strings(self, product: dict[str, Any]) -> set[str]:
        return {
            _norm(product.get(k))
            for k in ("brand_as_labelled", "generic_inn", "internal_sku", "gtin", "legacy_code")
            if product.get(k)
        }

    def scoped_aliases(self, tenant_code: str) -> list[dict[str, Any]]:
        return [
            a
            for a in self.pack.aliases
            if str(a.get("entity_kind")).upper() == "PRODUCT" and a.get("tenant_code") in (None, "", tenant_code)
        ]

    def _link(self, row, kind, tenant, left, right, status="SOURCE_ASSERTED", contract_id=None):
        return IdentityLink(
            kind=kind,
            tenant_code=tenant,
            source_sheet=row.get("_source_sheet"),
            source_row=row.get("_source_row"),
            verification_status=status,
            confirmed_by=row.get("confirmed_by"),
            confirmed_on=str(row["confirmed_on"]) if row.get("confirmed_on") else None,
            conflict_note=_note(row),
            source_tenant_code=row.get("tenant_code"),
            contract_id=contract_id,
            left=str(left or ""),
            right=str(right or ""),
            scope_basis="contract_registry"
            if contract_id
            else "unscoped_observation_candidate_only"
            if not row.get("tenant_code")
            else "tenant_source_claim",
        )

    def _alias_issues(self, a, tenant, as_of):
        issues = []
        note = _norm(_note(a))
        if str(a.get("same_real_world_thing") or "").upper() == "N":
            issues.append("NEGATIVE_RELATIONSHIP")
        if any(
            s in note
            for s in (
                "differs",
                "different",
                "not same",
                "not the same",
                "do not merge",
                "check before merging",
                "not interchangeable",
                "distinct",
            )
        ):
            issues.append("CONFLICTING_NOTE")
        elif note:
            issues.append("UNREVIEWED_CAVEAT")
        if a.get("tenant_code") != tenant:
            issues.append("UNSCOPED_ALIAS")
        if str(a.get("same_real_world_thing") or "").upper() != "Y" or not a.get("confirmed_by"):
            issues.append("UNCONFIRMED_ALIAS")
        if str(a.get("verification_status") or "").upper() in {"UNVERIFIED", "REJECTED", "CONFLICT"}:
            issues.append("UNCONFIRMED_ALIAS")
        if not a.get("_source_sheet") or not a.get("_source_row"):
            issues.append("MISSING_SOURCE_POSITION")
        try:
            confirmed = parse_date(a.get("confirmed_on"))
        except (ValueError, TypeError):
            confirmed = None
        if not confirmed or as_of is None or confirmed > as_of:
            issues.append("CONFIRMATION_NOT_IN_FORCE")
        return list(dict.fromkeys(issues))

    def _from_row(self, product, method, confidence, links):
        return ResolvedProduct(
            tenant_code=product.get("tenant_code") or "",
            match_method=method,
            confidence=confidence,
            brand=product.get("brand_as_labelled"),
            generic_inn=product.get("generic_inn"),
            internal_sku=product.get("internal_sku"),
            gtin=str(product["gtin"]) if product.get("gtin") else None,
            storage_spec_text=product.get("storage_spec_text"),
            permitted_excursion_text=product.get("permitted_excursion_text"),
            stability_study_ref=product.get("stability_study_ref"),
            light_sensitive=product.get("light_sensitive"),
            presentation_hint=_presentation_from_text(str(product.get("brand_as_labelled") or "")),
            candidates=[product],
            status="RESOLVED_SOURCE_ASSERTED",
            identity_links=links,
            release_identity_eligible=True,
        )

    def resolve_product(self, tenant_code: str, product_ref: Any, *, as_of: Optional[date] = None) -> ResolvedProduct:
        ref = _norm(product_ref)
        pool = [p for p in self.pack.products if p.get("tenant_code") == tenant_code]

        def unresolved(reasons, hits=None, links=None, status="UNRESOLVED"):
            return ResolvedProduct(
                tenant_code=tenant_code,
                match_method="ambiguous" if status == "UNRESOLVED_AMBIGUOUS" else "unresolved",
                confidence=0.0,
                candidates=hits or [],
                identity_links=links or [],
                status=status,
                reasons=list(dict.fromkeys(reasons)),
                unresolved_reason="; ".join(dict.fromkeys(reasons)),
                presentation_hint=_presentation_from_text(ref),
            )

        if not ref:
            return unresolved(["MISSING_PRODUCT_REFERENCE"])
        if not pool:
            return unresolved(["NO_TENANT_PRODUCT_POOL"])
        for key, kind, method in (("gtin", "EXACT_GTIN", "gtin_exact"), ("internal_sku", "EXACT_SKU", "sku_exact")):
            hits = [p for p in pool if p.get(key) and _norm(p[key]) == ref]
            if hits:
                links = [
                    self._link(p, kind, tenant_code, product_ref, p.get("internal_sku") or p.get("gtin")) for p in hits
                ]
                if len(hits) > 1:
                    return unresolved([f"AMBIGUOUS_{kind}"], hits, links, "UNRESOLVED_AMBIGUOUS")
                # A tenant-owned negative claim about the selected row's own
                # identifiers conflicts with that master assertion. Unowned
                # observations must not be silently assigned to this tenant.
                owned_conflicts = []
                conflict_reasons = []
                identifiers = self._product_strings(hits[0])
                for claim in self.scoped_aliases(tenant_code):
                    endpoints = {_norm(claim.get("string_a")), _norm(claim.get("string_b"))}
                    reasons = self._alias_issues(claim, tenant_code, as_of)
                    if (
                        claim.get("tenant_code") == tenant_code
                        and ref in endpoints
                        and endpoints <= identifiers
                        and any(r in {"NEGATIVE_RELATIONSHIP", "CONFLICTING_NOTE"} for r in reasons)
                    ):
                        owned_conflicts.append(
                            self._link(
                                claim, "ALIAS", tenant_code, claim.get("string_a"), claim.get("string_b"), "CONFLICT"
                            )
                        )
                        conflict_reasons.extend(reasons)
                if owned_conflicts:
                    return unresolved(conflict_reasons, hits, links + owned_conflicts, "UNRESOLVED_CONFLICT")
                return self._from_row(hits[0], method, 0.98 if key == "gtin" else 0.95, links)
        # Explore candidate claims without granting identity. Even an alternate
        # positive path cannot bypass a relevant negative/conflicting edge.
        rows = self.scoped_aliases(tenant_code)
        component = {ref}
        relevant = []
        changed = True
        while changed:
            changed = False
            for a in rows:
                ends = {_norm(a.get("string_a")), _norm(a.get("string_b"))} - {""}
                if ends & component:
                    if not any(a is old for old in relevant):
                        relevant.append(a)
                    if not ends <= component:
                        component |= ends
                        changed = True
        hits = [p for p in pool if self._product_strings(p) & component]
        if not hits:
            hits = [
                p
                for p in pool
                if any(
                    s and (ref in s or s in ref)
                    for s in (_norm(p.get("brand_as_labelled")), _norm(p.get("generic_inn")))
                )
            ]
        if not hits:
            return unresolved(["NO_TENANT_IDENTITY_MATCH"])
        links = []
        issues = []
        conflicts = []
        for a in relevant:
            reasons = self._alias_issues(a, tenant_code, as_of)
            issues.extend(reasons)
            conflicts.extend(r for r in reasons if r in {"NEGATIVE_RELATIONSHIP", "CONFLICTING_NOTE"})
            status = (
                "CONFLICT"
                if any(r in {"NEGATIVE_RELATIONSHIP", "CONFLICTING_NOTE"} for r in reasons)
                else "UNVERIFIED"
                if reasons
                else "CONFIRMED_SOURCE_ASSERTION"
            )
            links.append(self._link(a, "ALIAS", tenant_code, a.get("string_a"), a.get("string_b"), status))
        dimensions = _dimension_conflicts(component | {_norm(p.get("brand_as_labelled")) for p in hits})
        conflicts.extend(dimensions)
        if conflicts:
            return unresolved(conflicts + issues, hits, links, "UNRESOLVED_CONFLICT")
        if len(hits) > 1:
            return unresolved(["AMBIGUOUS_PRODUCT_CANDIDATES"] + issues, hits, links, "UNRESOLVED_AMBIGUOUS")
        target = hits[0]
        # Only owned, dated, confirmed, non-caveated edges may form an accepted path.
        paths = {ref: []}
        queue = deque([ref])
        while queue:
            node = queue.popleft()
            for a in relevant:
                if self._alias_issues(a, tenant_code, as_of):
                    continue
                left, right = _norm(a.get("string_a")), _norm(a.get("string_b"))
                neighbor = right if left == node else left if right == node else None
                if neighbor and neighbor not in paths:
                    paths[neighbor] = paths[node] + [a]
                    queue.append(neighbor)
        targets = self._product_strings(target) - {_norm(target.get("generic_inn"))}
        accepted = [paths[s] for s in sorted(targets) if s in paths and paths[s]]
        if accepted:
            path = min(accepted, key=len)
            path_links = [
                self._link(a, "ALIAS", tenant_code, a["string_a"], a["string_b"], "CONFIRMED_SOURCE_ASSERTION")
                for a in path
            ]
            return self._from_row(target, "alias_chain_confirmed", 0.8, path_links)
        if not links:
            links = [
                self._link(target, "ALIAS", tenant_code, product_ref, target.get("brand_as_labelled"), "UNVERIFIED")
            ]
        return unresolved(issues or ["PRODUCT_LEVEL_IDENTITY_NOT_ESTABLISHED"], hits, links, "UNRESOLVED_CANDIDATE")

    def resolve_facility(self, tenant_code: str, ref: Any) -> IdentityResolution:
        if not tenant_code or not _norm(ref):
            return IdentityResolution(reasons=["MISSING_TENANT_OR_FACILITY"])
        hits = [
            r
            for r in self.pack.facilities
            if r.get("tenant_code") in (None, "", tenant_code)
            and _norm(ref) in {_norm(r.get("code_in_source")), _norm(r.get("name_in_source"))}
        ]
        links = [
            self._link(
                r,
                "FACILITY",
                tenant_code,
                ref,
                r.get("code_in_source"),
                "SOURCE_ASSERTED" if r.get("tenant_code") == tenant_code else "UNSCOPED",
            )
            for r in hits
        ]
        if len(hits) > 1:
            return IdentityResolution("UNRESOLVED_AMBIGUOUS", ["AMBIGUOUS_FACILITY_RECORDS"], links, hits)
        if not hits:
            return IdentityResolution(reasons=["NO_TENANT_FACILITY_MATCH"])
        if hits[0].get("tenant_code") != tenant_code:
            return IdentityResolution("UNRESOLVED_OWNERSHIP", ["FACILITY_TENANT_OWNERSHIP_UNKNOWN"], links, hits)
        return IdentityResolution("RESOLVED_SOURCE_ASSERTED", links=links, candidates=hits, record=hits[0])

    def resolve_facility_canonical(self, ref: Any, *, tenant_code: Optional[str] = None) -> Optional[str]:
        """Compatibility lookup, UNUSED by engine/SOP resolution; no tenant, no hit."""
        result = self.resolve_facility(tenant_code or "", ref)
        return str(result.record["code_in_source"]) if result.record else None

    def resolve_carrier(
        self, tenant_code: str, carrier_ref: Any, as_of: Optional[date] = None, *, contract_id: Optional[str] = None
    ) -> IdentityResolution:
        if not carrier_ref or as_of is None:
            return IdentityResolution(reasons=["MISSING_CARRIER_OR_AS_OF_DATE"])
        ref = _norm(carrier_ref)
        active = []
        for c in self.pack.carriers:
            if c.get("tenant_code") not in (None, "", tenant_code):
                continue
            if contract_id and c.get("contract_id") != contract_id:
                continue
            start, end = c.get("_effective_from"), c.get("_effective_to")
            if (start and as_of < start) or (end and as_of > end):
                continue
            names = {_norm(n) for n in str(c.get("names_seen_on_documents") or "").split("|") if _norm(n)}
            active.append((c, _norm(c.get("counterparty_legal_entity")), names))
        tiers = (
            ("exact legal entity", lambda legal, names: ref == legal),
            ("exact alias", lambda legal, names: ref in names),
            ("substring candidate", lambda legal, names: any(ref in n or n in ref for n in names | {legal} if n)),
        )
        for method, predicate in tiers:
            hits = [c for c, legal, names in active if predicate(legal, names)]
            if not hits:
                continue
            links = [
                self._link(
                    c,
                    "LEGAL_ENTITY" if method == "exact legal entity" else "ALIAS",
                    tenant_code,
                    carrier_ref,
                    c.get("counterparty_legal_entity"),
                    contract_id=c.get("contract_id"),
                )
                for c in hits
            ]
            if len(hits) > 1:
                return IdentityResolution(
                    "UNRESOLVED_AMBIGUOUS",
                    [f"ambiguous carrier: {method} matches {[c.get('contract_id') for c in hits]}"],
                    links,
                    hits,
                )
            if method == "substring candidate":
                for link in links:
                    link.verification_status = "UNVERIFIED"
                return IdentityResolution("UNRESOLVED_CANDIDATE", ["CARRIER_SUBSTRING_NOT_IDENTITY"], links, hits)
            # The contract row is the legal-entity assertion, not a parent-group merge.
            if method == "exact alias":
                links.append(
                    self._link(
                        hits[0],
                        "LEGAL_ENTITY",
                        tenant_code,
                        hits[0].get("counterparty_legal_entity"),
                        hits[0].get("contract_id"),
                        contract_id=hits[0].get("contract_id"),
                    )
                )
            return IdentityResolution(
                "RESOLVED_SOURCE_ASSERTED", links=links, candidates=hits, record=hits[0], release_identity_eligible=True
            )
        return IdentityResolution(reasons=["NO_SCOPED_CARRIER_CONTRACT"])

    def resolve_carrier_contract(
        self,
        carrier_ref: Any,
        as_of: Optional[date] = None,
        *,
        tenant_code: Optional[str] = None,
        contract_id: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Legacy contract-scoped adapter; decision callers supply tenant explicitly."""
        result = self.resolve_carrier(tenant_code or "", carrier_ref, as_of, contract_id=contract_id)
        return result.record, "; ".join(result.reasons) or None
