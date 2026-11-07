# 06 · Testing and validation

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current typed identity evidence verification

Item 3 starts from `cf9b590`. Typed source/tenant/contract claims now block negative,
conflicting and unowned product aliases; unresolved products route to QA. This
changes identity routing, not clinical thresholds or source data.
[Failing/passing tests, commands and all changed events](validation/identity-evidence-review/report.md).

| Check | Observed result |
|---|---|
| Test-first regressions | 27 initial failures, then 1 release gate, 4 units/history, 1 owned-conflict failure before each fix; all 33 pass |
| Full pytest suite | 268 passed; one existing test-client dependency deprecation warning |
| Ruff lint / format | Passing |
| Fresh temporary run-all | 420 records |
| Recommendations | 0 AUTO_CLOSE / 383 QA / 37 unverified historical candidates; note/quarantine/destroy zero |
| Before / changed | 0 / 290 / 130; 93 historical candidates → identity QA; no closure/release increase |
| Verified closure counter | 0 |
| Independent obligations | Unchanged 28 conservative PENDING / 392 UNKNOWN |
| Full-result replay | 420/420 identical |
| Untouched tenant chains | All 8 OK; direct CLI verify exit 0 |
| Former alias-chain cases | All 81 unresolved (80 conflict, 1 candidate), all QA |
| API / UI / sealed evidence | Typed assessments and provenance; actual API and Node render retained |

The [evidence-chain review](validation/evidence-chain-review/report.md) retains its
235-test baseline and re-seal regressions. The [documentation review](validation/documentation-review/report.md)
retains the earlier 208-test run, source ZIP checks and original integrity probe.
These are versioned artifacts, not current outcome targets. Source data is unchanged.

These are regression/sample observations, not clinical truth, production rates,
validated legal applicability, throughput benchmarks or long-term durability proof.
All 420 sample legal deadlines remain null/UNKNOWN without approved policy inputs.

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
