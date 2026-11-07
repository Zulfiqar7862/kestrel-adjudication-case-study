# Typed identity evidence review — item 3 only

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Scope / inspected design

Baseline `cf9b590c493d9074bb7eb4869cd861aaf4792cba`; branch
`fix/correctness-review`; `/tmp/fixvenv` imports `/workspace/kprod/src/kestrel/__init__.py`.
The Claude review was read as ideas, not requirements or verified evidence; no
Claude code was copied. Items 4–8 were not started. Source data and notification
policy are unchanged. No clinical threshold, product truth or verified mapping
was invented.

`IdentityLink` records EXACT_GTIN, EXACT_SKU, ALIAS, LEGAL_ENTITY or FACILITY;
request scope, actual source ownership, physical sheet/row, source verification
status, confirmed_by/on, notes, endpoints and contract scope. New claims are
embedded in sealed evidence JSON, not an invented authoritative mapping table.
`tenant_code` on a projected candidate is the request scope; `source_tenant_code`
remains null for the workbook's unowned observations. Scope basis explicitly
labels them `unscoped_observation_candidate_only`, never tenant-confirmed.

A unique tenant master GTIN/SKU is SOURCE_ASSERTED, not independently verified.
Brand/INN/fuzzy matches remain candidates. Owned, source-positioned, dated,
confirmed, uncaveated alias paths can be accepted as confirmed **source assertions**;
actual source ownership must be explicit, never inferred from a QA name or a
shared product string. Relevant negative claims block alternate paths. Explicit
strength/presentation/unit conflicts require QA; no clinical unit conversion is
invented. Owned negative claims contradicting an exact master key also block it.
Unowned alias notes are not assigned a tenant or used to override an independent
tenant master-key lookup; such lookups do not traverse alias edges.

Unresolved product identity overrides provisional history with senior QA and
retains the previous rule plus historical classification. It cannot authorize
release/closure; release signing also refuses unverified/missing typed product
identity, including old bundles without it. Other clinical signing/authority gaps
remain. Carrier uncertainty is contract evidence, not a new clinical fate rule.
AFX-DE and Tapti exact priorities remain correct; a unique substring is now only
an unverified candidate, never a first-hit legal identity.

Facility lookup now refuses ambiguity/unknown ownership. It is deliberately
**UNUSED_NOT_AUTHORITY_INPUT** in engine/SOP selection, visible in evidence/API/UI.
Wiring a tenantless shared registry into governing site annexures would invent
ownership and expand into item 5; this pass does neither.

## Test-first evidence (executed)

Before any production edit: **27 failed in 4.77s** ([red](red.txt)). Additional
regressions were then added and observed failing before their specific changes:
**1 release-gate failure** ([gate](gate-red.txt)); **4 unit/history failures**
([extra](extra-red.txt)); **1 owned master-conflict failure** ([owned](owned-red.txt)).
Afterwards **33 passed in 5.18s** ([named passing output](green.txt)); the final
repeat, with explicit in-force dates in weak/foreign-alias fixtures, had
**33 passed in 4.86s** ([repeat](green-final.txt)).
Missing APIs/fields failed with AttributeError/TypeError; merge bugs failed by
returning the SKU or wrong disposition. Existing correct AFX-DE/Tapti contract
selection is a positive control augmented with the previously missing typed
provenance, not falsely reported as a new wrong-contract bug. The UI helper was
executed in Node with escaped adverse notes, not merely searched as text.

Each row quotes the first observed failure line; long lines are shortened here
only. Full traces and named passing output are retained.

| Test in `tests/test_identity_evidence.py` | Failing output | After |
|---|---|---|
| `test_negative_alias_comments_block_merge[Strength differs \u2014 check before merging]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_negative_alias_comments_block_merge[Same molecule, different presentation]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_real_negative_alias_rows[84]` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_real_negative_alias_rows[86]` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_multihop_never_crosses_strength_or_presentation[Drug 20mg PFS]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_multihop_never_crosses_strength_or_presentation[Drug 40mg vial]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_weak_or_foreign_alias_never_authorizes_release[unconfirmed]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_weak_or_foreign_alias_never_authorizes_release[unowned]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_weak_or_foreign_alias_never_authorizes_release[negative]` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_weak_or_foreign_alias_never_authorizes_release[foreign]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_weak_or_foreign_alias_never_authorizes_release[conflicting-alternate]` | `AssertionError: assert 'SKU-A' is None` | PASSED |
| `test_scoped_confirmed_alias_retains_every_hop` | `TypeError: IdentityResolver.resolve_product() got an unexpected keyword argument 'as_of'` | PASSED |
| `test_future_confirmation_is_not_current_identity` | `TypeError: IdentityResolver.resolve_product() got an unexpected keyword argument 'as_of'` | PASSED |
| `test_exact_links_have_tenant_and_real_source[EXACT_GTIN-001234]` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_exact_links_have_tenant_and_real_source[EXACT_SKU-SKU-A]` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_duplicate_gtin_is_explicit_ambiguity` | `AttributeError: 'ResolvedProduct' object has no attribute 'release_identity_eligible'` | PASSED |
| `test_cross_tenant_master_is_never_used` | `AttributeError: 'ResolvedProduct' object has no attribute 'status'` | PASSED |
| `test_carrier_contract_scoped_provenance[AFX-DE-CNT-2023-0441]` | `AttributeError: 'IdentityResolver' object has no attribute 'resolve_carrier'` | PASSED |
| `test_carrier_contract_scoped_provenance[Tapti Exp Cargo-CNT-2021-0245]` | `AttributeError: 'IdentityResolver' object has no attribute 'resolve_carrier'` | PASSED |
| `test_carrier_ambiguity_and_foreign_scope` | `AttributeError: 'IdentityResolver' object has no attribute 'resolve_carrier'` | PASSED |
| `test_facility_duplicate_name_is_not_first_hit` | `AttributeError: 'IdentityResolver' object has no attribute 'resolve_facility'` | PASSED |
| `test_unowned_facility_is_explicitly_unused` | `AttributeError: 'AdjudicationResult' object has no attribute 'identity_evidence'` | PASSED |
| `test_all_previous_alias_chain_events_are_candidates_only` | `AttributeError: 'ResolvedProduct' object has no attribute 'status'` | PASSED |
| `test_source_row_numbers_survive_blank_rows` | `TypeError: sheet_rows() got an unexpected keyword argument 'include_source'` | PASSED |
| `test_api_and_sealed_evidence_show_unresolved_identity` | `KeyError: 'identity_evidence'` | PASSED |
| `test_release_signing_cannot_promote_unverified_alias` | `Failed: DID NOT RAISE TransitionError` | PASSED |
| `test_ui_renders_identity_status_and_escapes_source_notes` | `assert ('function identityPanel' in '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,...tenant", "disp"].forEach((id) => $(id).addEventListener("input"` | PASSED |
| `test_unverified_identity_blocks_even_an_earlier_release` | `AssertionError: assert 'RELEASE_WITH_NOTE' == 'ESCALATED_TO_SENIOR_QA'` | PASSED |
| `test_incompatible_strength_units_cannot_be_merged[Drug 40mcg PFS]` | `AssertionError: assert 'RESOLVED_SOURCE_ASSERTED' == 'UNRESOLVED_CONFLICT'` | PASSED |
| `test_incompatible_strength_units_cannot_be_merged[Drug 4g PFS]` | `AssertionError: assert 'RESOLVED_SOURCE_ASSERTED' == 'UNRESOLVED_CONFLICT'` | PASSED |
| `test_incompatible_strength_units_cannot_be_merged[Drug 40mg/mL PFS]` | `AssertionError: assert 'RESOLVED_SOURCE_ASSERTED' == 'UNRESOLVED_CONFLICT'` | PASSED |
| `test_historical_text_cannot_hide_unresolved_product_identity` | `AssertionError: assert 'HISTORICAL_C...TE_UNVERIFIED' == 'ESCALATED_TO_SENIOR_QA'` | PASSED |
| `test_owned_negative_claim_conflicting_with_exact_master_key_blocks_identity` | `AssertionError: assert 'RESOLVED_SOURCE_ASSERTED' == 'UNRESOLVED_CONFLICT'` | PASSED |

## Executed full/sample verification

[Exact commands](commands.txt); [expanded direct CLI commands](executed-cli-commands.json).

- **268 passed, 1 warning in 51.00s** ([full](pytest.txt)); a fresh repeat also
  passed **268 tests in 50.67s** ([repeat](pytest-final-recheck.txt)). Existing Starlette/httpx
  dependency deprecation only. Ruff lint and format pass.
- Fresh temp run-all: **420 records**, **0 AUTO_CLOSE / 383 QA / 37 unverified
  historical candidates**, verified closures **0**, release/quarantine/destroy
  **0/0/0**. Before was **0 / 290 / 130**. Independent notifications remain
  **28 PENDING / 392 UNKNOWN**. These are sample counts, not production accuracy.
- **420/420 full-result replays identical**, all **8 untouched chains OK**
  ([verification](verification.json)); direct CLI verify/replay exit 0
  ([verify](cli-verify.json), [replay](cli-replay.json)). The evidence-chain fix
  remains exercised by the full suite; no evidence storage code was changed.
- Every one of the **93 changed outcomes** was inspected and checked to be a
  historical candidate → QA through `typed_identity_unresolved_gate`:
  **77 conflict / 13 missing or unmatched / 3 unverified candidate** identities;
  **66 duplicate / 27 facility-no-load** historical classifications. The original
  classifications remain reference evidence, not verified closure eligibility.
  [All changed events and reasons](changed-events.md), [machine-readable](outcome-changes.json).
  No QA case became a closure or release. Final deciding rules change for 287
  unresolved products, including 194 already-QA cases; prior rules/traces remain.
- The **81 previously alias_chain** cases were frozen before implementation:
  **80 UNRESOLVED_CONFLICT / 1 UNRESOLVED_CANDIDATE**, all QA, no adopted SKU.
  [Full 81-case table](alias-cases.md) lists every event, tenant, raw reference,
  old SKU, new state/reasons, physical alias rows and before/after disposition.
  [All 420 results](all-outcomes.csv), [summary](inspection.json).
- EXC-112289 is now UNRESOLVED_CONFLICT, not SKU-INS-0442 identity: the row-83
  observation is unowned, and its candidate component includes row 81's different
  presentation caveat and future confirmation claims. It remains QA; deciding
  rule is now typed identity review. No study was selected to imitate history.
- [Actual API JSON](api-EXC-112289.json) shows the assessment, also sealed at
  `inputs.resolution.identity`. Adjudicate/event endpoints and OpenAPI have typed
  identity fields. [Actual Node-rendered panel](ui-identity-panel.html) shows the
  state, reasons, source positions, confirmation claims and unused facility marker.
  No complete browser-driven workflow or production security test is claimed.

## Existing tests/expectations changed, and why

The [first integration attempt](full-initial.txt) had **15 failed / 248 passed**.
Tests caught an over-broad carrier-to-product-fate guard and JSON date objects in
new candidate metadata: the former was removed (carrier liability is not a new
clinical rule), and assessments now return JSON-native metadata. Boundary,
firmware and immutable-original-artifact assertions were preserved; the targeted
integration run subsequently passed 97 tests, then the full suite passed.

After inspecting the real final 383/37 run, count assertions in `test_api.py`,
`test_historical_candidates.py`, `test_ops.py` and the health report's sample drift
reference were changed from 130/290 to 37/383. No count target drives decisions.
Historical-candidate API/evidence/CLI fixtures moved from EXC-112198 (missing
product, correctly now QA) to EXC-112394 (exact tenant SKU and historical duplicate,
still an unverified candidate). All separation/signature/history assertions remain.
EXC-112198 is retained in the 93-event audit table; its old closure category was
not silently preserved to pass a test.

The prior `test_unique_carrier_substring_still_works` expectation was replaced by
`test_unique_carrier_substring_is_candidate_not_verified_identity`: a partial
string retains its contract candidate and UNVERIFIED link but cannot establish
legal identity. Exact AFX-DE/Tapti and ambiguity tests remain. This is an explicit
identity policy correction, not weakening tests to fit counts.
The capture helper no longer asserts equality with an old outcome distribution;
it still requires all 420 replays identical and all tenant chains valid, while
recording every changed event. This permits evidence-driven count movement.

## Limits / inspected rather than executed guarantees

The workbook supplies no tenant-owned product alias registry. No real alias was
upgraded to independently verified identity. Confirmation names/dates are source
claims, not authenticated reviewer credentials, and descriptor checks are not a
complete product ontology or qualified clinical equivalence assessment. Current
master/reference rows are not universally knowledge-time filtered; alias date
checks do not prove what was actually known at the alert.

Facility ownership/site linkage stays unused; governing SOP/annexure resolution,
full study discovery, dependency-triggered re-review, precedent import and curation
workflows remain outside this item. Most API routes still lack production user
and tenant authorisation; request scoping is not caller authentication. Local
SQLite/files are not an independent anchor: rewriting both can forge evidence.
Clinical readiness, hostile admin protection, concurrency/scale and external
source truth are unvalidated. These limits come from inspected design, not claims
of successful production or clinical validation.

Docs 03/04/07, current counts, LLD/ER/pipeline PNGs and retained Mermaid sources
were updated after inspecting the run; the EXC-107133 GIF/sidecar were refreshed
from that actual run. All PNG/GIF copies are under `/workspace/final-visuals/`
([manifest](visual-manifest.json)). No merge, PR or force-push; commit and watched
CI result are reported separately after the normal branch push. Then stop.
