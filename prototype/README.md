# Prototype — as-of adjudication engine

## What I built (and why)

The component that would keep me up at night is not a dashboard. It is the **deterministic as-of adjudication engine**: given a real excursion alert from the pack, resolve product identity, apply sensor-bulletin corrections, select the SOP revision in force on the excursion date, interpret stability / permitted-excursion text (including presentation mismatch), bind the carrier contract, compute the regulatory deadline, and emit a recommendation **plus a structured evidence basis**.

Why this over the LLM assistant or the UI:

- January pilot invented studies; INC-2411’s prompt edit destroyed USD 310k of insulin.
- AUD-2603 / March inspection failed on missing as-of evidence, not on missing chrome.
- Dr Rao allows automation on **closures**, not on signed decisions — the engine must be diffable and replayable.

LLM justification drafting, the workbench, and live ingest are stubbed on purpose.

## Layout

```
prototype/
  requirements.txt
  run.py                 # CLI entry
  src/adjudication/
    pack.py              # loads the real xlsx tabs
    identity.py          # GTIN/SKU/brand/alias + carrier contract
    as_of.py             # SOP-as-at + storage range parse
    stability.py         # allowance resolution + presentation check
    regulatory.py        # windows from tab 13 / tab 12 positions
    engine.py            # decision logic
    cli.py
  tests/                 # unit, golden, invariants
  output/                # results.csv, summary.txt, showcase_evidence.json
```

## Setup

```bash
cd prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run against the real workbook

```bash
cd prototype
source .venv/bin/activate
python run.py
# or a single case:
python run.py --event EXC-107133
```

Writes:

- `output/results.csv` — one row per alert (420 in the pack)
- `output/summary.txt` — recommendation mix, bulletin count, agreement diagnostics
- `output/showcase_evidence.json` — full evidence for EXC-107133 and selected overrides

## Tests

```bash
cd prototype
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected: **15 passed**.

### How correctness is verified today

| Layer | What |
|---|---|
| Unit | Identity (GTIN/Tapti), SOP overlap on T-KAVERI 2026-07-28, storage-range parse |
| Golden | EXC-107133 → `RELEASE_WITH_NOTE`; TT-2.14.3 bulletin +1.8°C; facility-storm AUTO_CLOSE; freeze-risk cases not waved through |
| Invariants | AUTO_CLOSE ⇒ no human signature required; actionable ⇒ human required; reportable ⇒ deadline ≥ alert; SOP `effective_from` ≤ excursion date; bulletin monotonic |
| Replay CLI | Full 420-row run; diagnostic agreement vs historical finals / assistant column |

### How we keep it reliable at 03:00 six months from now

1. **Golden set growth** — every signed disagreement and every override reason (tab 09) becomes a pinned case.
2. **Shadow mode** — new `rule_pack_semver` scores in parallel before promotion (`docs/02-design.md` §5).
3. **Rule-version replay** — evidence bundle stores `rule_pack_semver` + `ref_snapshot_id` + `git_sha`; offline re-exec must bit-match the stored recommendation.
4. **Dr Rao gate** — diff report required before every change that can move dispositions (board condition).
5. **Never optimise raw agreement with history** — pack README: the “rules_engine_recommendation” column is the 2024+ LLM draft. Agreement is a diagnostic. Explaining diffs is the product.

## Design notes discovered in the pack (also in `working-log/LOG.md`)

- T-KAVERI Glucodyne SoloJet cites vial study STB-3584; engine prefers master cumulative-72h text and flags mismatch.
- “Cumulative 72 h above 8 °C” is a time-above-threshold budget, not `max_temp ≤ 8`.
- SOP overlap soft-flags rather than hard-stops when stability is decisive.
- Facility-storm rows with blank product_ref triage before identity escalate.
