# 06 · Testing and validation

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current verification (final state, `production`)

Executed on a fresh venv against the unchanged 420-alert workbook.

| Check | Observed result |
|---|---|
| Full pytest suite | 325 passed |
| Ruff lint / format | Passing |
| Fresh run-all | 420 records |
| Recommendations | 0 AUTO_CLOSE / 383 QA / 37 unverified historical candidates; note/quarantine/destroy zero |
| Verified closure counter | 0 |
| Independent obligations | 28 conservative PENDING / 392 UNKNOWN; all 420 legal deadlines UNKNOWN |
| Full-result replay | 420/420 identical |
| Tenant evidence chains | All 8 verify |
| Docs link check | Passing |

## Per-fix reports (history, test-first)

Each report states its own baseline; counts there describe that version, not current behaviour.

| Fix | Report |
|---|---|
| Missing temps, carrier, cumulative, study/SOP authority | [correctness review](validation/correctness-review/report.md) |
| Storage limits | [storage limits](validation/storage-limits-review/report.md) |
| Historical candidates | [historical candidates](validation/historical-candidates-review/report.md) |
| Notification obligations | [notifications](validation/notification-obligations-review/report.md) |
| Evidence-chain re-seal | [evidence chain](validation/evidence-chain-review/report.md) |
| Typed identity evidence (93 candidates → identity QA) | [identity evidence](validation/identity-evidence-review/report.md) |
| Study discovery with typed rejection reasons | [study discovery](validation/study-discovery-review/report.md) |
| Documentation/visuals and integrity probe | [documentation review](validation/documentation-review/report.md) |

These are regression/sample observations, not clinical truth, production rates,
validated legal applicability, throughput benchmarks or long-term durability proof.

## Reproduce the main checks

From an installed fresh venv at the repository root:

```bash
python -m pytest
python -m ruff check
python -m ruff format --check
mkdir -p /tmp/kestrel-docs-check
kestrel --log-level WARNING --db /tmp/kestrel-docs-check/run.sqlite \
  --evidence-dir /tmp/kestrel-docs-check/evidence run-all \
  --out /tmp/kestrel-docs-check/results.csv > /tmp/kestrel-docs-check/run-all.json
python docs/diagrams/capture_run.py --run-dir /tmp/kestrel-docs-check \
  --case-output /tmp/kestrel-docs-check/EXC-107133.json
python docs/diagrams/check_links.py
```

Create `/tmp/kestrel-docs-check` first; use a fresh directory on each rerun. The
capture command reuses that persisted run, performs all replays/chain checks and
saves actual EXC-107133 values. It does not sign or send. [Visual regeneration](diagrams/README.md).

## What the suite covers — and what it does not

Coverage includes temperature-bound semantics and missing data, carrier ambiguity,
cumulative refusal, study/SOP authority, historical candidate surfaces, signed
artifact hashes, replay/tamper cases and independent notification persistence and
scoped access. Green tests do not establish unauthenticated API safety, qualified
clinical rules, source truth, verified receipt delivery, realistic storm behaviour,
residency compliance or seven-year source reconstruction.

[Versioned historical validation archive](validation/README.md) keeps failing and
passing evidence from earlier changes. Old outcome counts and limitations are
labelled by version there; they are not current acceptance targets. Historical
finals/assistant drafts are references, not clinical gold labels or count targets.
