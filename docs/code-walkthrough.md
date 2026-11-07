# Current code walkthrough (rule/code 0.4.2)

These specific defects were addressed; overall safety and production readiness remain unvalidated.

This is the corrected flow, checked on 7 Nov 2026 (CET). The earlier 0.4.0 walkthrough described an unsafe product-master fallback; it is no longer the implementation. Source workbook and PDF are unchanged. Executed outputs and test-first logs are linked in [validation](validation/correctness-review/report.md).

## 1. Read the real shipment record

`DataPack.load` in `src/kestrel/ingest.py` reads the workbook. `AdjudicationService.adjudicate_event` in `src/kestrel/service.py` looks up EXC-107133 and calls `AdjudicationEngine.adjudicate` in `src/kestrel/engine.py`.

Actual row: tenant T-KAVERI, shipment SHP-KAV-418802, leg 2, GTIN 08901234500035, Bhiwandi Hub → Kundli Pharma Store, carrier Tapti Exp Cargo, firmware TT-2.15.0. Reported extrema are 5.4°C and 11.2°C, mean 7.9°C, duration 15 minutes. Original records remain intact.

## 2. Assemble reference candidates

`IdentityResolver.resolve_product` in `src/kestrel/rules/identity.py` resolves the GTIN within T-KAVERI. This is actual matching over manually curated workbook data, not verified master-data integration. Alias observations remain unverified candidate links.

`parse_storage_limits` in `src/kestrel/rules/as_of.py` extracts the labelled 2–8°C range. `StabilityResolver.resolve` in `src/kestrel/rules/stability.py` examines the uniquely cited tenant study STB-3584. It cannot establish product/presentation/excursion-type applicability, so returns `source="unresolved"`, no parsed allowance and an explicit `authority_issue`. It does not substitute master cumulative-allowance prose or assume an uncited study is correct.

`sop_in_force` in `rules/as_of.py` still returns an indexed highest-revision candidate and all overlapping revisions. For this case SOP-KAV-9392 Rev03 overlaps another revision; this is not resolution of governing authority. `engine.adjudicate` additionally marks SOP/site authority unresolved because actual SOP bodies/site annexures are not supplied in the workbook.

`IdentityResolver.resolve_carrier_contract` resolves Tapti Exp Cargo to CNT-2021-0245, whose row lacks a cold-chain schedule. Legal entity exact matches precede exact aliases, then unique substring candidates. AFX-DE now selects German CNT-2023-0441; ambiguous matches produce an error preserved in evidence rather than a guessed contract.

## 3. Evaluate facts, not historical agreement

`decision_rules.decide` runs these gates before ordinary triage:

1. `parse_storage_limits` preserves explicit bound type and strict/inclusive semantics. Missing required extrema/invalid supplied values are a measurement QA reason; unclear storage text is a separate QA reason. Upper-only requires max, lower-only requires min, two-sided requires both. Neither mean nor a nominal LN2 value supplies a missing bound. Additional restrictions are kept separately and not independently verified. Historical triage cannot waive either guard.
2. If the applicable allowance is cumulative and an excursion exists, verified batch identity and complete prior history are unavailable: QA. Arbitrary event fields claiming zero previous exposure do not certify anything. In-range observations require no lifetime-exposure arithmetic.
3. The remaining fixed rules run. An excursion with unresolved study applicability routes to QA.
4. A final authority gate covers **every** release recommendation, including early gateway and fallback paths, plus allowance-based closures. Missing governing SOP/site content, overlapping revisions, or unresolved study authority blocks those outcomes.

For EXC-107133, complete temperatures pass the first gate. The study is unresolved, not a usable cumulative allowance; `rule_stability_authority` returns `ESCALATED_TO_SENIOR_QA`, confidence 0. It no longer gives RELEASE_WITH_NOTE merely to agree with history. No batch exposure is inferred, subtracted or written.

## 4. Preserve and replay

`AdjudicationService._persist`, `storage/evidence.py` and `storage/bitemporal.py` preserve the event/reference snapshot, full result and tenant hash-chain links. `replay_from_bundle` restores sealed inputs and compares the full result without consulting the current workbook. Rule/code version is 0.4.2; old executable runtimes are not archived by this helper. Index records are preserved, **not** missing raw temperature series, study PDFs or SOP annexures.

`requires_human_signature=True` means a recommendation needs human review. Signers are typed names, not authenticated people, and manual sign-off still does not independently enforce site-authority clearance. This is not production release control.

## 5. Firmware uncertainty and comparison cases

TT-CB-114 means under-reporting **up to** 1.8°C, not an exact correction. The engine retains observations and evaluates reported and upper-bound summary scenarios. EXC-107133 is unaffected firmware. The sample shadow run has 91 candidates, 91 scenario/evidence diffs and zero disposition flips after the conservative gates; this does not establish firmware safety or reproduce the historical 61-flip incident.

EXC-112289 remains QA, now stopped earlier by unresolved study identity/presentation; its historical quarantine outcome is not assumed correct. EXC-112198 still AUTO_CLOSEs on historical duplicate text with sufficient extrema/label bounds; no live deduplication proof was built. That remaining historical-triage dependence is explicitly labelled **unverified historical classification, not independent duplicate verification** in the trace and evidence. All current sample closures are duplicate/facility historical classification; see the [full inventory](validation/storage-limits-review/report.md).

## Reproduce

```bash
python3 -m venv /tmp/fixvenv
. /tmp/fixvenv/bin/activate
pip install -e '.[api,dev]'
python -c 'import kestrel; print(kestrel.__file__)'
pytest -o addopts='' -q
ruff check .
ruff format --check .
kestrel --db /tmp/reviewer/state.sqlite --evidence-dir /tmp/reviewer/evidence run-all --out /tmp/reviewer/results.csv
kestrel --db /tmp/reviewer/state.sqlite --evidence-dir /tmp/reviewer/evidence adjudicate --event EXC-107133
```

Sample counts: 130 AUTO_CLOSE, 290 QA, 0 release-with-note/quarantine/destroy. These are not production-accuracy estimates or QA-approved clinical outcomes.
