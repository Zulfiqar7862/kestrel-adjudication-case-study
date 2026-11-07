# 07 · Limitations, inspection concerns and roadmap

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current limitations: do not deploy on these assumptions

| Area | Current gap / inspection finding | Status |
|---|---|---|
| Identity | Typed scoped claims now retain provenance and reject negative/conflicting/weak product aliases; actual workbook aliases have no tenant ownership, so none are promoted | Source assertions are not authenticated independent verification; full owner curation/ontology remains needed |
| Study discovery | All tenant index rows now have typed reasons and strength/presentation checks; supplied study approval/effective/knowledge/supersession metadata and full reports are absent | No admissible sample selection; no authenticated full-report authority or inferred alternate mapping |
| SOP/site annexures | Effective-date metadata and overlaps are visible, but indexed body/site annexure content is absent | Release authority unresolved; explicit resolution-task workflow not implemented |
| Batch exposure | No verified batch identity or complete prior-exposure/once-only-use history | Cumulative assessment cannot assume zero |
| Clinical rules | Numeric freeze/ultra-cold/gap/allowance heuristics still exist; other storage restrictions are not verified | No universal safety/production validation |
| Signing | Release signing now requires typed product identity, but name/hash/state checks do not authenticate authority, prove viewing, enforce all other evidence blockers or implement real two-person signing | Existing workflow/security concern; not fixed here |
| General HTTP API | Most case/evidence/dashboard routes lack authenticated tenant ownership checks; notification lane alone has scoped grants | Not a production tenant wall |
| Notification operations | No approved policy/calendar registry, live sender/retry worker, verified filing receipt or pager; references never clear obligations | 28 pending / 392 unknown in this sample are not verified legal-reportability counts |
| Evidence/storage | Local mutable JSON + SQLite; file/index publication is non-atomic; concurrent chain writers unvalidated; raw source series/PDF archive incomplete | Not WORM, HA or seven-year recovery evidence |
| Integrity reads | Shared file/index/whole-tenant reconciliation now guards retrieval, basis, signing and replay; this costs a full tenant scan and blocks on unrelated damage | Local consistency, not authenticated provenance or an independent anchor |
| Point-in-time knowledge | Main calculation reads a current workbook DataPack; interval tables do not provide universal historical knowledge-time enforcement | Sealed replay is narrower than no-hindsight reconstruction |
| Namespace/security | Alert event IDs are global keys; tenant strings feed privileged local paths; caller-owned tenant IDs are not a general auth mechanism | Production namespace/path/access review required |
| Source changes | No general source-dependency index with affected-case re-review/reopen tasks | Unfinished |
| Precedents/curation | No production tenant-partitioned reasoning import with decision-known-before-alert filtering, or evidence-completeness-conditioned disagreement/curation backlog | Unfinished |
| Operations | No validated tenant fairness, incident admission, live bulletin feed, delivery/clock paging or load/restore benchmark | Health dictionaries/queue ordering are not deployed operational guarantees |

The other gaps above are code-inspection findings and known limitations, not new
executed exploit or clinical outcome claims. The identity fix adds scoped evidence and unresolved-product QA gates, not clinical
thresholds or new source data. Facility resolution remains explicitly unused for
site/SOP authority. All 81 former alias-chain promotions now remain unresolved:
80 conflict and 1 candidate. No source aliases were granted invented tenant ownership. Executed sample/replay checks are listed
separately in [validation](06-testing-and-validation.md).

## Evidence integrity: addressed defect and remaining trust limit

The [previous isolated probe](validation/documentation-review/integrity-probe.json)
showed a re-sealed tail passing with a different indexed hash. The current
[regression report](validation/evidence-chain-review/report.md) records failing
then passing tests for that defect, middle re-sealing, missing/replaced files,
index/file mismatches, orphan files, predecessor checks and tenant placement.
All evidence consumers share the verifier through `get()`; signing and replay
cannot accept a re-sealed bundle or a child whose tenant chain is inconsistent.
The [probe utility](diagrams/probe_integrity.py) now expects rejection.

**SQLite plus local files is not an independent anchor. Someone who can rewrite
both can still forge a consistent history.** Deleting matching files and index
rows together, including an entire chain, cannot be detected without an external
head/count/checkpoint. No external timestamp authority, signed root, immutable
backup or WORM archive was added. Reconciliation is not an atomic cross-store
snapshot, and concurrent publication/restore/failure behaviour is unvalidated.
These are trust/design limitations from code inspection, not executed claims
that a joint-store forgery was prevented. Signing still does not authenticate a
person's authority or establish clinical release eligibility.

## Roadmap: proposed, not implemented

1. Populate and authenticate the implemented typed identity claims through qualified
   tenant owners. Supplied aliases remain unowned/unverified candidates. Source QA
   names/dates are claims, not authenticated signatures; current master rows are not
   a universal no-hindsight archive. Exact tenant GTIN/SKU assertions do not establish
   source truth. Incompatible explicit descriptors require review, not invented unit
   conversion or clinical equivalence. Facility ownership/site linkage remains unestablished.
2. Qualify the implemented [study discovery catalogue](validation/study-discovery-review/report.md)
   with tenant owners, controlled full reports and verified alternate mappings.
   Discovery remains separate from clinical release authority; source approvals
   and effective/knowledge/supersession metadata are not manufactured.
3. Obtain controlled site/date SOP bodies and annexures; create open resolution
   tasks for missing/overlapping authority. Blank transcription must never clear a blocker.
4. Establish verified batch/once-only history and source dependencies; create
   human re-review/reopen tasks for changed sources.
5. Import precedents/reasoning only within the tenant and only when the decision
   existed before the alert; avoid hindsight and incomplete-evidence accuracy claims.
6. Build curation/completeness metrics and qualified retrospective review, not a
   target number of automatic closures.
7. Deploy authenticated/dual-authority workflows, authorised policy/calendar
   registry, independent notification workers/verified receipts/paging, retention,
   concurrency/restore tests and tenant/residency controls before production review.

Prior proposed items are not delivered by documenting them. The branch remains
unmerged for owner review. No source data, clinical rule or verification was invented.
