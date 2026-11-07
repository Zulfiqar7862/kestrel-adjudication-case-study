# 07 · Limitations, inspection concerns and roadmap

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current limitations: do not deploy on these assumptions

| Area | Current gap / inspection finding | Status |
|---|---|---|
| Identity | Product master pool is tenant scoped, but aliases marked Y are traversed without honouring comments such as strength/presentation differences; generic INN/fuzzy matches may promote a unique row | Existing correctness concern; not changed by the integrity fix |
| Study discovery | Only the cited study is resolved; no full candidate/rejection catalogue, strength-controlled discovery or authenticated full-report authority | Unfinished; no study ID hard-coded as a remedy |
| SOP/site annexures | Effective-date metadata and overlaps are visible, but indexed body/site annexure content is absent | Release authority unresolved; explicit resolution-task workflow not implemented |
| Batch exposure | No verified batch identity or complete prior-exposure/once-only-use history | Cumulative assessment cannot assume zero |
| Clinical rules | Numeric freeze/ultra-cold/gap/allowance heuristics still exist; other storage restrictions are not verified | No universal safety/production validation |
| Signing | Name/hash/state checks do not authenticate authority, prove viewing, enforce all evidence blockers or implement real two-person signing | Existing workflow/security concern; not fixed here |
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
executed exploit or clinical outcome claims. The focused integrity fix changes no
clinical decision rules or source data. Executed sample/replay checks are listed
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

1. Have qualified owners curate typed tenant identity claims, including negative
   strength/presentation relationships and ownership/knowledge-time evidence.
2. Discover study candidates with explicit product/strength/presentation/type/
   readability reasons; keep discovery separate from clinical release authority.
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
