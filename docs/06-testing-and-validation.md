# 06 · Testing and validation

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Current evidence-chain fix verification

The focused integrity change starts from `0bb2337`. It changes evidence
reconciliation, consumer error handling and CLI verification status, not clinical
rules, source data or notification policy. [Failing/passing tests and commands](validation/evidence-chain-review/report.md).

| Check | Observed result |
|---|---|
| Test-first regressions | 25 initial failures; 2 additional field-presence failures before that fix; then all 27 pass |
| Full pytest suite | 235 passed; one existing test-client dependency deprecation warning |
| Ruff lint / format | Passing |
| Fresh temporary `run-all` | 420 sample records persisted |
| Recommendations | 0 AUTO_CLOSE / 290 QA / 130 unverified historical candidates; note/quarantine/destroy zero |
| Verified closure counter | 0; no outcome/count changes |
| Independent obligations | 28 conservative PENDING / 392 UNKNOWN |
| Full-result sealed-input replay | 420/420 identical |
| Untouched tenant evidence chains | All 8 OK; direct CLI verify exit 0 |
| Isolated re-sealed tail | Rejected with INDEX_HASH_MISMATCH; direct CLI exit 1 |
| API consumers on damaged evidence | Verify returns ok:false; basis/replay/sign return 409 with reason |
| Existing test fixture repair | Original tamper assertions retained; cleanup restores shared file after test |

The [previous documentation review](validation/documentation-review/report.md)
retains its 208-test baseline, source ZIP/SHA-256 check, visuals and the original
unfixed integrity probe. Those artifacts describe that earlier revision, not the
current verifier. Source data remains unchanged.

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
