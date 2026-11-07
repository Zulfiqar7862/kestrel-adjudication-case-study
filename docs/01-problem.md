# 01 · The problem and its evidence

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Start with the custody record, not a disposition label

The [brief, page 1](../data/Case_Study_Brief_Adjudication.pdf#page=1) explains that
Kestrel's product is the evidence a customer's pharmacist needs. The medicine and
regulatory obligation belong to the customer. This prototype addresses a small
part of evidence assembly; it does not establish the right to release medicine.

| Source | What it establishes | Design implication, not a verified production result |
|---|---|---|
| Brief pp. 1–2 | Alerts arise outside labelled limits; real product-fate decisions need a named human | Separate summaries/recommendations from an authorised disposition |
| [Brief p. 2](../data/Case_Study_Brief_Adjudication.pdf#page=2), EXC-107133 | Product aliases, pen/vial studies, site/date SOP annexures, lane and carrier evidence obstruct review | Assemble dated references; refuse unsupported study/release authority |
| [Brief p. 3](../data/Case_Study_Brief_Adjudication.pdf#page=3) | Cumulative exposure and later audit reconstruction matter; a firmware bulletin gives an upper uncertainty bound | Do not assume zero previous exposure or an exact temperature correction |
| [Brief p. 4](../data/Case_Study_Brief_Adjudication.pdf#page=4) | Notification and disposition have different clocks; invented reasoning is unacceptable | Keep durable notification work independent; expose uncertainty |
| [Brief pp. 5–6](../data/Case_Study_Brief_Adjudication.pdf#page=5) | Earlier model pilots fabricated references; board wants disagreement evidence and long-term reconstruction | Deterministic calculations and retained test/replay evidence, not a polished demo as proof |
| [Brief pp. 6–7](../data/Case_Study_Brief_Adjudication.pdf#page=6) | Nine systems lack a common identity model; alias observations are unverified and sometimes wrong | Tenant-specific evidence needs curation, negative relationships and ownership |
| [Brief p. 7](../data/Case_Study_Brief_Adjudication.pdf#page=7) | Design must explain interfaces, state, ordering, failure and recovery | Keep HLD/LLD, code limits and executed checks distinct |

## What was supplied

The ZIP's two substantive files are byte-identical to the two files in `data/`:
[brief PDF](../data/Case_Study_Brief_Adjudication.pdf) and
[reference workbook](../data/KCCS_Sentinel_Reference_Data_Pack.xlsx).
It also contains one macOS resource-metadata entry; this is not an additional
requirement or runtime input. [SHA-256 inventory](validation/documentation-review/source-check.json).
No source file was changed. The engine reads the workbook, not the PDF at runtime.

The workbook is a hand-assembled, stratified sample, not a random production
population. Its README, reviewer questions, source-system inventory, constraints,
clocks/costs and incident log are context. Only selected sheets are loaded by
`DataPack`; there are no live connectors to those nine systems.

## What this prototype can answer

It can show the supplied measurements, selected master/index records, unresolved
authority, a deciding rule and saved inputs. It cannot prove that the raw series,
identity, complete prior batch exposure, governing annexure or human authority are
valid. The brief's historical RELEASE_WITH_NOTE for EXC-107133 is not a golden
clinical answer to force into the current run.

[HLD](02-hld.md) · [Limits and unfinished work](07-limitations-and-roadmap.md).
