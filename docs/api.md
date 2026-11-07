# HTTP API

These specific defects were addressed; overall safety and production readiness remain unvalidated.

Start it with `kestrel serve` (or `make serve`, or Docker). Interactive OpenAPI docs are at
`http://127.0.0.1:8080/docs`, and the reviewer dashboard is at `/ui`.

POST request bodies are JSON where present; sign/reopen use query parameters. Validation errors return `422`, unknown ids `404`, cross-tenant reads `403`, and a
signature against stale evidence `409`.

## Adjudication

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/health` | – | `ok`, `snapshot_id`, `rule_pack_version` |
| `POST` | `/adjudicate` | `{"event_id": "EXC-107133", "persist": true}` | recommendation, confidence, rationale, `bundle_id`, `case_id`, `reg_deadline_utc` |
| `GET` | `/events` | `tenant_code` (optional) | every alert with its recommendation |
| `GET` | `/events/{event_id}` | – | full detail used by the dashboard |

## Historical candidates (0.4.3)

`POST /adjudicate`, `GET /events` items and `GET /events/{id}` expose typed recommendation enums and explicit review/eligibility fields in OpenAPI. Example excerpt from the executed EXC-112198 response:

```json
{
  "event_id": "EXC-112198",
  "recommendation": "HISTORICAL_CLOSURE_CANDIDATE_UNVERIFIED",
  "historical_classification": "NON_ACTIONABLE — duplicate of earlier alert",
  "closure_eligibility": "historical_candidate_unverified",
  "independent_closure_evidence": [],
  "requires_human_review": true,
  "requires_human_signature": true,
  "case_state": "PENDING_EVIDENCE"
}
```

This is unresolved human-review routing, not product fate or verified AUTO_CLOSE eligibility. The original historical text is preserved, not certified. No independent duplicate/load verification artifact is supplied. Candidate signing as a final disposition or automatic closure is refused. Human-authority/authentication and evidence-attachment workflows remain incomplete.

`/ops/health-report`, `/ops/agreement`, `/events`, service run-all summaries and CLI batch/single outputs preserve the distinction. Their shared `closure_counts` is:

```json
{"verified_auto_close": 0, "historical_candidates_unverified": 130, "other_auto_close_unverified": 0}
```

AUTO_CLOSE labels from legacy numeric rules, if ever emitted, are not silently counted as independent verification. Current pack has no verified-closure adapter. `/ui` renders these counts on the server and uses candidate badges/reference warnings in case details; the unresolved review category is excluded from final-sign options.

Bundles record the same fields in `recommendation`, original classification in `inputs.alert.historical_classification`, and source/limitations in `inputs.resolution.closure_assessment` plus the rule trace. [Executed JSON/schema/UI excerpt](validation/historical-candidates-review/report.md).

## Evidence

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/evidence/{bundle_id}` | `tenant_code` (required) | the sealed bundle; `403` for another tenant |
| `POST` | `/evidence/basis` | `{"event_id": "...", "tenant_code": "..."}` | captured basis (latest signature artifact after signing), local latency, retention metadata |
| `POST` | `/evidence/verify` | `{"tenant_code": "T-KAVERI"}` | hash-chain check for that tenant |
| `POST` | `/replay` | `{"bundle_id": "...", "tenant_code": "..."}` | verified bundled event/references, full-result comparison; rejects missing inputs/version mismatch |

## Cases

| Method | Path | Query | Notes |
|---|---|---|---|
| `GET` | `/cases/{case_id}` | – | current case record |
| `POST` | `/cases/{case_id}/sign` | `signed_by`, `disposition`, `reason`, `bundle_hash` | mandatory name and viewed `bundle_hash`; missing hash/blank name `422`, stale/tampered hash or closed case `409`; appends SIGNED artifact |
| `POST` | `/cases/{case_id}/reopen` | `reason` | creates a new linked case revision carrying deadline/reportability |
| `GET` | `/queue` | `tenant_code`, `limit` (1–500) | open cases ordered by regulatory deadline |

## Reference and operations

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/as-of/sop` | `tenant_code`, `date=YYYY-MM-DD` | SOP revision in force that day, plus any overlap |
| `GET` | `/shadow/bulletin` | – | TT-CB-114 bound-aware vs reported-only diffs, disposition_flips and QA-review instruction (no enforced approval gate) |
| `GET` | `/ops/health-report` | – | alert catalogue for on-call (deadlines, chain, drift, feed age) |
| `GET` | `/ops/agreement` | – | agreement with historical decisions, by reason, tenant and firmware |

## Example session

```bash
curl -s -X POST localhost:8080/adjudicate -H 'content-type: application/json' \
  -d '{"event_id":"EXC-107133"}'
# → "recommendation":"ESCALATED_TO_SENIOR_QA", "bundle_id":"EVB-…", "case_id":"CASE-…"

curl -s -X POST localhost:8080/evidence/verify -H 'content-type: application/json' \
  -d '{"tenant_code":"T-KAVERI"}'
# → "ok": true

curl -s -X POST "localhost:8080/cases/CASE-…/sign?signed_by=A.%20Rao&disposition=RELEASE_WITH_NOTE&bundle_hash=<content_hash>"
```

Version0.4.0 replaces `corrected_max_temp_c` with `reported_max_temp_c`; `/events/{id}` exposes `uncertainty.scenarios`, never a calibrated +1.8 truth. The API has no authentication/role or mandated dual-sign enforcement. Evidence reads require a tenant parameter, not proof of caller ownership. Production must authenticate and authorise every route.
