# Operations runbook

## Configuration

Every setting has a default and can be overridden with an environment variable (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `KESTREL_DATA_PACK` | `data/KCCS_Sentinel_Reference_Data_Pack.xlsx` | Reference workbook |
| `KESTREL_DB_PATH` | `<tmp>/kestrel-adjudication/kestrel.sqlite` | SQLite store |
| `KESTREL_EVIDENCE_DIR` | `<tmp>/kestrel-adjudication/evidence` | Sealed bundle JSON files |
| `KESTREL_LOG_LEVEL` | `INFO` | JSON log level |
| `KESTREL_API_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in Docker) |
| `KESTREL_API_PORT` | `8080` | HTTP port |

CLI flags `--db`, `--pack`, `--evidence-dir` and `--log-level` override the environment.

## Running

| How | Command |
|---|---|
| Local | `make install && make serve` |
| Docker | `make docker-build && make docker-run` |
| One-off batch | `kestrel run-all --out results.csv` |

The Docker image runs as a non-root user, stores state in `/var/lib/kestrel` (mount a volume there to keep it),
and has a `HEALTHCHECK` on `/health`.

## What to check at 3 am

Run `kestrel health` (or `GET /ops/health-report`). Each signal has a severity and a firing flag.

| Signal | What it means | First action |
|---|---|---|
| `regulatory_deadline_breached` | A reportable case passed its notification deadline | File the notification from the evidence bundle now; the disposition can follow |
| `regulatory_deadline_at_risk` | Deadline is close and the case is unsigned | Page the on-call reviewer for that market |
| `evidence_chain_verification_failure` | A tenant's hash chain does not verify | Freeze signing for that tenant, run `kestrel verify --tenant T`, find the first bad bundle |
| `decision_mix_drift` | Outcome mix moved away from baseline | Check for a new firmware bulletin or reference-data load before trusting closures |
| `data_feed_staleness` | Reference data is stale | Reload with `kestrel ingest --reload` once the source is fixed |
| `firmware_bulletin_change` | A logger firmware bulletin applies to open alerts | Run the shadow replay before trusting closures |
| `queue_age` | Cases are waiting too long | Add reviewers; the queue is already deadline-ordered |

The regulatory clock is never paused by an outage. If the engine is down, cases fall back to the human queue,
which is ordered by deadline (`kestrel queue`).

## Releasing a rule change

1. Change the rule and its boundary tests (`tests/test_decision_rules.py`).
2. Run `make lint test`.
3. Replay the whole pack and review every changed outcome (`kestrel shadow-bulletin` shows the pattern for the
   TT-CB-114 change).
4. Bump `rule_pack_version` so new bundles record which rules produced them.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

* lint and tests on Python 3.10, 3.11, 3.12 and 3.13, plus a CLI smoke test;
* a Docker build that starts the container and calls `/health`, `/ui` and `/adjudicate`.
