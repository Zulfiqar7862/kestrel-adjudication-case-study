# 06 · Testing and validation

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## What was executed for this documentation pass

The engine, tests, package configuration and source data are unchanged from
`62c498f7110d6aa335194097da3c28b522aaf9ec`. New Python files are documentation
capture/render/link-check utilities only. [Run report and exact commands](validation/documentation-review/report.md).

| Check | Observed result |
|---|---|
| Full pytest suite | 208 passed; one test-client dependency deprecation warning |
| Ruff lint / format | Passing; no engine/test source edits |
| Fresh temporary `run-all` | 420 sample records persisted |
| Recommendations | 0 AUTO_CLOSE / 290 QA / 130 unverified historical candidates; note/quarantine/destroy zero |
| Verified closure counter | 0; other unverified numeric AUTO_CLOSE counter also 0 |
| Independent obligations | 28 conservative PENDING / 392 UNKNOWN |
| Comparison with previous verified CSV | No recommendation changed |
| Full-result sealed-input replay | 420/420 identical |
| Tenant evidence chains | All 8 OK |
| ZIP/data verification | Two substantive files match SHA-256; one macOS metadata entry; data/ unchanged |
| Isolated integrity probe | Re-sealed reasoning edit can pass chain verification despite indexed-hash mismatch; reported, not fixed |
| Local links / image paths | Checked by the documentation link utility; see retained result |

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
python docs/diagrams/capture_run.py --run-dir /tmp/kestrel-docs-check
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
