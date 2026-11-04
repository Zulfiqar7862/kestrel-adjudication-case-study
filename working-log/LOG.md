# Working log — Zulfiqar Ali Ahmed

Timestamps are Europe/Berlin (box clock). This log is what actually happened while reading the pack and building the submission; it is not a reconstructed narrative.

## 2026-11-04 ~10:36 — Opened the brief and pack

Read `Case_Study_Brief_Adjudication.pdf` end-to-end (`pdftotext -layout`) and dumped all 15 tabs of `KCCS_Sentinel_Reference_Data_Pack.xlsx`.

First reaction I discarded: treat this as “build a better LLM recommendation assistant.” Section 5 already burned the January full-LLM pilot (invented studies, withdrawn SOP revs) and INC-2411 (prompt edit → USD 310k destroyed). Marieke’s versioning demand and Dr Rao’s “automation on closures, not decisions” make a model-first design the wrong centre of gravity.

Second reaction I discarded: prototype the reviewer UI / evidence browser. Visual, not the hard correctness problem. The brief’s EXC-107133 story is about whether fifteen minutes at 11.2 °C is permitted for *this* presentation under the revision in force *that day* — that is an as-of rules / reference-data problem.

**Kept:** prototype the as-of adjudication engine (identity → stability → SOP-as-at → contract → regulatory clock → disposition recommendation + evidence basis).

## 2026-11-04 ~10:40 — Pack README surprises (assumptions that were wrong)

I had assumed `rules_engine_recommendation` was the 2023 rules engine. Pack README line 45: since 2024 that column is the **recommendation assistant’s draft**; nobody renamed it. Agreement rates against that column are therefore comparing me to an LLM draft, not to Sandeep’s 2,400 rules.

I had assumed tab 01 was a statistical sample. It is **stratified** (61 bulletin re-adjudications + 24 overrides + late notifications + INC-2502 slice + EXC-107133 + random remainder). Population ratios live on tab 13 only.

Timestamps: alerts UTC, reviewer log local, facility timezone wrong for two sites. Regulatory clock runs from `alert_ts_utc`, not `excursion_start_utc` (detection latency). I almost wired the deadline off excursion start; caught it in the README.

## 2026-11-04 ~10:50 — EXC-107133 vs the product master (data contradiction)

Brief: Glucodyne SoloJet, GTIN `08901234500035`, 15 min at 11.2 °C, stability permits a single excursion ≤6 h below 15 °C, Priya released with note.

Pack row EXC-107133 matches the narrative (T-KAVERI, Tapti Exp Cargo, USD 96,400, final `RELEASE_WITH_NOTE`, note about 1.5-day reconstruction).

But T-KAVERI product master for that GTIN cites **STB-3584**, which `06_Stability_Index` labels **“Glucodyne SoloJet … — vial”** with blank `permitted_excursion_text` (Partial scan). Master `permitted_excursion_text` says “Cumulative 72 h above 8 °C…”. That is the EXC-110497 failure mode sitting inside the hero case itself.

**Position taken:** when brand implies pen/SoloJet and the cited study is indexed as vial, prefer the master permitted-excursion text, flag presentation mismatch, reduce confidence, still require human signature. Do not silently trust the mismatched study.

Also: “cumulative 72 h above 8 °C” means a **time-above-threshold budget**, not `max_temp ≤ 8`. My first parser treated 8 as a cap and wrongly quarantined EXC-107133. Fixed after the golden test failed; logged because this is exactly the class of bug that incinerates insulin.

## 2026-11-04 ~11:00 — SOP overlap: escalate vs proceed

T-KAVERI `SOP-KAV-9392` Rev 01/02/03 have overlapping effective windows on 2026-07-28 (pack confirms what the brief describes). First engine version hard-escalated on any overlap. That disagreed with the brief: overlapping SOPs did **not** change Priya’s outcome once stability was clear.

**Position taken:** record the conflict in the evidence pack, require human confirmation of which acceptance limit governed, but continue stability arithmetic. Hard-escalate only when the decision *depends* on the contested limit and stability is absent/Refer QA/unreadable.

## 2026-11-04 ~11:05 — Facility storm vs blank product_ref

INC-2502 rows often have blank `product_ref_as_received`. Identity-first escalation marked them `ESCALATED_TO_SENIOR_QA` before facility triage ran — the opposite of what you want in an alert storm. Reordered: facility-equipment / duplicate triage before identity escalate.

## 2026-11-04 ~11:10 onward — Docs and rollout positions

Discarded “first customer = Virent (largest volume).” Board minute: one customer and certain. Aurastat (T-AURA) has the conditional renewal and AUD-2603 — evidence reconstructability is the go-live gate, not throughput. Virent is phase 2 (and prohibits external model APIs — tab 12).

Discarded chasing board commitment #2 (70% closed without a person) as a primary KPI. 82% of alerts are non-actionable; today’s engine already auto-closes ~64% of all alerts. Pushing automation into *decisions* is what Dr Rao refused. I argue the board should accept “≥78% of non-actionable auto-closed with audited evidence” plus human on all product-fate dispositions.

AI use this session: heavy for scaffolding and first-pass prose; every numeric claim checked against the pack; golden tests pinned to pack rows so confident-but-wrong recommendations fail loudly.

## Decisions snapshot

| Decision | Why |
|---|---|
| Prototype = as-of adjudication engine | Hardest correctness surface; maps to Q1–Q2, Q10, AUD-2603 |
| No LLM in the prototype path | January pilot + INC-2411; LLM later drafts text from assembled evidence only |
| First tenant = T-AURA | Conditional renewal; EU residency already matches Marieke; board “one and certain” |
| Push back on 70% no-human and 34-in-9-months | Conflicts with Dr Rao + board minute; see `docs/01-where-you-land.md` |
| Bitemporal evidence store in design | March inspector request; seven-year / one-hour board commitment |

## 2026-11-04 ~10:43 — Full pack run (420 events)

```
AUTO_CLOSE 224 (53.3%)
ESCALATED_TO_SENIOR_QA 80
DESTROY 31
QUARANTINE_PENDING_LAB 31
RELEASE_WITH_NOTE 54
bulletin applied 91
sop overlaps 13
agree historical final 14/200 (7%)
agree historical assistant column 206/420 (49%)
EXC-107133 → RELEASE_WITH_NOTE ✓
pytest 15 passed
```

Low agreement with historical finals is expected and acceptable for this submission: the engine escalates `Refer QA` allowances, presentation mismatches without usable master text, and missing SOPs rather than guessing RELEASE. Dr Rao asked for diffs explained, not agreement maximised. I am not tuning toward the 7%.

## 2026-11-04 ~10:47 — Docs committed

Where-you-land, design, diagrams, prototype README, top README. Pushing incrementally to `main`.

## 2026-11-04 ~10:57–11:05 — Production hardening pass

Asked to take the submission to production level without touching `data/`. Prioritised per brief: evidence (3) → bitemporal store (2) → tests (7) → lifecycle (4) → shadow (5) → package (1) → docs (8) → API/Docker/CI (6).

### What I kept from the prototype
Engine decision logic, golden EXC-107133 behaviour, bulletin correction, presentation-mismatch handling. Ported into `src/kestrel_sentinel/` rather than rewriting — prototype tests still pass (15/15).

### What I added
- SQLite bitemporal store; workbook load creates snapshot `ref_snapshot_id`.
- Evidence bundles: content hash + per-tenant hash chain; tamper test flips disposition to DESTROY and `verify_chain` fails.
- Tenant isolation test: T-PINNACLE/T-MERIDIAN cannot read T-KAVERI bundle.
- Lifecycle with reopen-months-later creating a linked case revision.
- Shadow bulletin CLI: 91 TT-2.14.3 candidates, 91 diffs when bias removed (sampled 15 in `examples/`).
- FastAPI smoke tests via TestClient.

### Measured
EXC-107133 full-basis retrieval **0.72 ms** locally (`examples/retrieval_latency.txt`). Retention stamped to 2033 (7 years).

### Discarded during this pass
- Postgres / separate object store — SQLite + filesystem is enough to prove the audit properties under the time box; swap-out is a boundary (`EvidenceStore` / `BitemporalStore`).
- Re-implementing the engine in Pydantic models end-to-end — would burn the window; kept dataclass engine, added Pydantic at API/domain edges.
- Committing `.data/` evidence for all 420 events — too large/noisy; committed EXC-107133 sample + 25-row CSV instead. Full run: `kestrel adjudicate`.

### Still incomplete
Live ingest, OCR annexures, batch cumulative ledger, LLM drafter (still deliberately out of decision path). API authn/z beyond tenant_code query param — production would use mTLS + tenant claims; called out as follow-on.
