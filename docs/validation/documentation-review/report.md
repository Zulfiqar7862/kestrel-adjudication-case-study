# Documentation and visuals review

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Scope

Baseline: `62c498f7110d6aa335194097da3c28b522aaf9ec`, branch
`fix/correctness-review`. This pass changes README/docs and documentation-only
capture/render/check/probe utilities. Engine, tests, source data, package/dependency
configuration, Makefile and CI workflow are unchanged. No clinical rule or
verification was invented. No merge, PR or force-push was performed. CI is watched
after the documentation commit is normally pushed; its final URL/result is reported separately.

## Source ZIP and unchanged data

[SHA-256 inventory](source-check.json) confirms the ZIP's two substantive files
match the files already in `data/` byte-for-byte:

- Brief: `d9d94b8f0bbe8d7a723d5fac3560f568c7193f22dd250a4ae38046b6ba61205b`.
- Workbook: `9fe3fad7d0f77a5fbdaa0f8ce70336a911a8725d38d057b9d9d777c06ea57db3`.

A third ZIP entry is macOS resource metadata (`__MACOSX/._...pdf`), not another
brief, requirement or runtime input. Nothing was extracted over `data/`.
The brief was re-read with page boundaries using poppler; citations in
[the problem guide](../../01-problem.md) refer to the PDF's page numbers.

## Structure and visuals

The [README](../../../README.md) is now a plain-English entry point with five
problem lines, scope, fresh-venv quickstart, actual example, counts and limitations.
The canonical guide has [problem](../../01-problem.md), [HLD](../../02-hld.md),
[LLD](../../03-lld.md), [system design](../../04-system-design.md),
[workflow](../../05-workflow.md), [validation](../../06-testing-and-validation.md)
and [limitations/roadmap](../../07-limitations-and-roadmap.md).

Old `architecture.md`, `case-study.md`, `code-walkthrough.md`, `decision-rules.md`,
`operations.md` and `api.md` are short navigation redirects, not competing
implementation descriptions. Existing historical validation reports/logs remain
unchanged; their index explicitly distinguishes versioned experiments from current behaviour.

[Visual manifest](visual-manifest.json) lists the eight PNGs and nine-frame GIF,
dimensions, hashes and copies under `/workspace/final-visuals/`:

- `hld.png`
- `lld.png`
- `data-model.png`
- `case-lifecycle.png`
- `notification-lifecycle.png`
- `decision-pipeline.png`
- `evidence-chain.png`
- `workflow-decision.png`
- `workflow.gif`

All are real rendered files and embedded in Markdown. The seven design diagrams
have [retained sources](../../diagrams/README.md) and matching inline Mermaid.
Pillow renders the PNG/GIF; Graphviz installation was unavailable because the
package repository returned HTTP errors. No repository-signature check was
relaxed and no headless browser was used.

The GIF's nine stages and still use only values from
[the actual current run JSON](../../images/workflow-run.json), retained beside the
GIF and copied alongside the visuals. Long records explicitly point to the full
JSON. This is not a reviewer recording, real-time performance demonstration or
completed legal filing. No disposition was signed and no notification was sent.

## Executed verification (not code-inspection claims)

Actual commands are in [commands.txt](commands.txt).

- Full pytest: **208 passed, 1 warning in 31.52s** ([output](pytest.txt)); unchanged
  from the baseline's 208 tests. The warning is Starlette/httpx deprecation.
- Ruff lint and format checks pass ([lint](ruff.txt), [format](format.txt)).
- Fresh temporary run-all: **420 records** ([summary](run-all.json)).
- Recommendations: **0 AUTO_CLOSE / 290 QA / 130 unverified historical candidates**;
  release-with-note, quarantine and destroy all zero. Verified closures **0**.
- Independent lane: **28 conservative PENDING / 392 UNKNOWN**. These are not
  independently verified legal-reportability counts. All legal deadlines remain
  null/UNKNOWN without approved scope/calendar evidence.
- No recommendation changed against the prior verified CSV. Full-result replay:
  **420/420 identical**; all **8 tenant chains OK** on the untouched primary run
  ([verification](verification.json)). This does not refute the isolated integrity
  defect below or prove authenticated/WORM integrity.
- CLI example returns QA with `rule_stability_authority`
  ([actual CLI output](cli-example.json)).
- Local Markdown link targets, fragments, inline Mermaid matching, PNG/GIF
  signatures and embedding are checked by the retained utility
  ([result](links.json)). No external Markdown URLs required HTTP validation.
- PNG/GIF files were decoded and GIF has nine frames; copies match their source
  hashes ([manifest](visual-manifest.json)).
- `git diff --quiet 62c498f -- src tests data pyproject.toml Makefile .github`
  succeeds. Source hashes were rechecked, and no bytecode is tracked.

## Doc claims removed or corrected

These are documentation corrections, not new engine fixes:

| Earlier wording/implication removed with the old narratives | Current description |
|---|---|
| Prefer product-master allowance prose when study presentation conflicts | Cited-study mismatch stays unresolved; master text is not substituted |
| A match/alias chain proves the same product/presentation | Tenant master matching is source-asserted; negative comments/strength and alias ownership remain known gaps |
| A selected highest SOP revision establishes governing authority | It is indexed metadata; overlaps and missing body/site-annexure authority remain unresolved |
| Hash-bound signing proves the named human saw/was authorised for the evidence | It checks supplied hash/name/state; actual viewing, identity, clinical clearance and dual authority are not established |
| Per-tenant files/query parameters imply a complete tenant wall | Most API routes lack production user auth; only the notification HTTP lane has explicit scoped grants |
| Bitemporal columns mean universal no-hindsight/as-known-at-alert reconstruction | The engine reads a current workbook DataPack; sealed replay reproduces captured inputs, not all historical knowledge |
| Hash-chain OK or append-only wording proves immutable/WORM evidence | Local files are mutable; cross-store writes/concurrency/retention are unvalidated, and the tail/index binding defect below is demonstrated |
| Case queue ordering or health dictionaries are a deployed storm/paging service | No validated admission/fairness, real pager, legal filing transport or HA clock service exists |
| Legacy empirical goals, runtime/retention checks or historical agreement prove production safety/performance | Board goals are context; the stratified sample and local checks are not production accuracy, capacity, time-saving or seven-year recovery evidence |
| Multiple old walkthroughs/count tables are equally current | One structured guide is canonical; historical reports remain clearly versioned |

The already-correct 0/290/130 counts, notification uncertainty and required
readiness disclaimer were retained, not claimed as new behavioural improvements.
Unsupported implementation-era marketing/effort/SLA implications were removed
rather than restated as measured results. Source-code comments/docstrings were
not edited in this documentation-only pass; where their wording overstates a
guarantee, the current guide states the narrower inspected behaviour.

## Bug noticed: isolated executed integrity defect, not fixed

In an isolated temporary single-bundle store copied from an actual bundle, the
probe appended a clearly labelled local-only reasoning line and recomputed the
core content hash. It did not change the SQLite indexed hash. `verify_chain()`
still returned **ok: true**, while `file_hash_differs_from_index` was **true**.

[Probe output](integrity-probe.json) · [reproduction utility](../../diagrams/probe_integrity.py).
The primary run, real source files, clinical recommendation and engine code were
untouched. No signing bypass was tested: signing has separate indexed-hash checks.
This defect is reported for a later code task, not silently fixed or hidden by
208 green tests. A chain-OK report must not be treated as an authenticated root guarantee.

## Code-inspection concerns, separately labelled

Identity Y-alias traversal ignores negative/caveated comments and can promote
molecule/fuzzy matches. Study discovery, source-dependency re-review, precedent
knowledge-time filtering and a curation backlog remain unfinished. Name/hash
signing is not authenticated clinical authority. File/index writes and concurrent
chain publication are not transactional. Most API routes lack a production tenant
security boundary. These are inspected/known limitations, not additional new
executed exploit or clinical outcome claims. See the [complete limitations](../../07-limitations-and-roadmap.md).
