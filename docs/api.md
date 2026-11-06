# HTTP API

Start it with `kestrel serve` (or `make serve`, or Docker). Interactive OpenAPI docs are at
`http://127.0.0.1:8080/docs`, and the reviewer dashboard is at `/ui`.

All POST bodies are JSON. Validation errors return `422`, unknown ids `404`, cross-tenant reads `403`, and a
signature against stale evidence `409`.

## Adjudication

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/health` | – | `ok`, `snapshot_id`, `rule_pack_version` |
| `POST` | `/adjudicate` | `{"event_id": "EXC-107133", "persist": true}` | recommendation, confidence, rationale, `bundle_id`, `case_id`, `reg_deadline_utc` |
| `GET` | `/events` | `tenant_code` (optional) | every alert with its recommendation |
| `GET` | `/events/{event_id}` | – | full detail used by the dashboard |

## Evidence

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/evidence/{bundle_id}` | `tenant_code` (required) | the sealed bundle; `403` for another tenant |
| `POST` | `/evidence/basis` | `{"event_id": "...", "tenant_code": "..."}` | full basis, retrieval latency, retention date |
| `POST` | `/evidence/verify` | `{"tenant_code": "T-KAVERI"}` | hash-chain check for that tenant |
| `POST` | `/replay` | `{"bundle_id": "...", "tenant_code": "..."}` | re-runs the decision from the bundle and compares |

## Cases

| Method | Path | Query | Notes |
|---|---|---|---|
| `GET` | `/cases/{case_id}` | – | current case record |
| `POST` | `/cases/{case_id}/sign` | `signed_by`, `disposition`, `reason`, `bundle_hash` | `422` if `signed_by` is blank, `409` if `bundle_hash` is stale or the case is already signed |
| `POST` | `/cases/{case_id}/reopen` | `reason` | creates a new linked case revision |
| `GET` | `/queue` | `tenant_code`, `limit` (1–500) | open cases ordered by regulatory deadline |

## Reference and operations

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/as-of/sop` | `tenant_code`, `date=YYYY-MM-DD` | SOP revision in force that day, plus any overlap |
| `GET` | `/shadow/bulletin` | – | TT-CB-114 before/after diff and the release gate result |
| `GET` | `/ops/health-report` | – | alert catalogue for on-call (deadlines, chain, drift, feed age) |
| `GET` | `/ops/agreement` | – | agreement with historical decisions, by reason, tenant and firmware |

## Example session

```bash
curl -s -X POST localhost:8080/adjudicate -H 'content-type: application/json' \
  -d '{"event_id":"EXC-107133"}'
# → "recommendation":"RELEASE_WITH_NOTE", "bundle_id":"EVB-…", "case_id":"CASE-…"

curl -s -X POST localhost:8080/evidence/verify -H 'content-type: application/json' \
  -d '{"tenant_code":"T-KAVERI"}'
# → "ok": true

curl -s -X POST "localhost:8080/cases/CASE-…/sign?signed_by=A.%20Rao&disposition=RELEASE_WITH_NOTE&bundle_hash=<content_hash>"
```
