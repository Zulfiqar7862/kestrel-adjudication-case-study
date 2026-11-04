# Kestrel Cold Chain Solutions — The Adjudication Problem

Case study submission by **Zulfiqar Ali Ahmed**.

## Executive summary

Kestrel’s adjudication pain is not “the model is not smart enough.” It is that a reviewer cannot, in one place, see the **as-of** product identity, stability allowance, SOP revision, lane history, and carrier contract that justify a signed disposition — and cannot reproduce that basis a year later (AUD-2603). I would build an **evidence-centred, bitemporal adjudication platform** that auto-closes non-actionable alerts deterministically, recommends (never auto-signs) actionable dispositions with an immutable evidence bundle, and keeps the regulatory clock independent of the disposition clock.

**First customer:** Aurastat Biologics (`T-AURA`) within 90 days — conditional renewal, EU residency, board “one and certain.”

**Prototype:** the as-of adjudication engine, run against the real 420-row workbook.

**Board pushback:** I reject chasing “70% closed with no human” into decision automation, and I reject a hard “all 34 in nine months” over residency/competitor constraints. Detail in [`docs/01-where-you-land.md`](docs/01-where-you-land.md).

## How to run the prototype

```bash
cd prototype
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                  # processes data/KCCS_Sentinel_Reference_Data_Pack.xlsx
python -m pytest tests/ -v     # 15 tests
```

Outputs land in `prototype/output/`.

## Navigation

| Path | Contents |
|---|---|
| [`docs/01-where-you-land.md`](docs/01-where-you-land.md) | Requirements↔cites, non-goals, phased rollout, gaps, board pushback |
| [`docs/02-design.md`](docs/02-design.md) | Architecture, data model, lifecycle, degradation, versioning |
| [`docs/diagrams/`](docs/diagrams/) | Mermaid: architecture, case lifecycle, as-of query |
| [`prototype/`](prototype/) | Working as-of engine + tests + CLI |
| [`working-log/LOG.md`](working-log/LOG.md) | Discarded ideas, wrong assumptions, pack contradictions |
| [`data/`](data/) | Brief PDF + reference pack (inputs only) |

## Time spent

On the order of a focused working day inside the suggested 10–14 h band (reading pack deeply, engine+tests, design writing, incremental commits).
