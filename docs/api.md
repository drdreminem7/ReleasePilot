# Local API, investigation queue and evaluation history (M3–M5)

Prerequisites: complete the [lab setup](lab.md) through `make sample-up`, then
run `make db-up` and `make db-migrate`. The database is a dedicated PostgreSQL
18 container on `127.0.0.1:15432`; never place its generated password in a
command, source file, screenshot or report. `scripts/with-postgres.sh` loads
the Git ignored password file for commands.

Run `make register-lab` to verify the active context, node UID, namespace
annotation and `checkout-api` Deployment UID before inserting the workload
registration. Run `make user-add USER=<name> ROLE=operator` to create a local
account; the command prompts twice for a password of 12–256 characters. Use
`ROLE=viewer` for a read-only account. Both commands create audit records.

In separate terminals run `make run-api` and `make run-worker`. API binds only
to `127.0.0.1:8000`. Worker claims queued investigations in PostgreSQL with
`FOR UPDATE SKIP LOCKED` and runs the M4 graph. Without a Gemini key, it
records `PROVIDER_UNAVAILABLE` and no diagnosis. For a labeled deterministic
run, set `RELEASEPILOT_PROVIDER=fixture` in the worker environment. It never
writes to Kubernetes. Run the worker once using:

```bash
cd backend
bash ../scripts/with-postgres.sh .venv/bin/python -m releasepilot.worker --once
```

`GET /health/live` reports process liveness and `GET /health/ready` verifies
database access plus the expected Alembic revision. `POST /api/v1/auth/login`
accepts JSON `username` and `password`, returning an eight hour opaque bearer
token. Only its SHA-256 digest is stored in PostgreSQL. Use the token in the
`Authorization: Bearer ...` header; keep it out of shell history and logs.
`POST /api/v1/auth/logout` revokes it.

An operator can `POST /api/v1/investigations` with JSON
`{"workload_id":"<registered UUID>"}` and a unique `Idempotency-Key` header
of 8–120 safe characters. The API verifies the current local lab identity and
workload UID before returning `202` and a durable `QUEUED` record. Reuse of a
key by the same operator returns `409`. `GET /api/v1/investigations` supports
`limit` (1–100), `offset`, and `state`; detail and `/events` endpoints return
the stored lifecycle. `GET /api/v1/workloads` includes observed health or
explicit `UNKNOWN` when the lab read fails. `GET /api/v1/audits` is operator
only. Errors include a safe code and a `request_id`; the same ID is in the
`X-Request-ID` response header.

`GET /api/v1/investigations/{id}/evidence` returns bounded stored evidence
with IDs, sources, timestamps, resource versions and content digests. A graph
report appears in investigation detail only after persistence succeeds.
`GET /api/v1/evaluations` is available to authenticated viewers and supports
`run_id`, `limit` and `offset`. Rows include the explicit replay source mode,
provider, prompt version, fixture digest, normalized scores and observed
artifacts. See the [evaluation runbook](evaluation.md) for how rows are created.

`GET /api/v1/workloads/{id}/metrics?metric=scrape_up&version=v1` is available
to authenticated viewers after `make monitoring-up`. The metric catalog is
`scrape_up`, `request_rate`, `error_ratio`, and `latency_p95`; only `v1` and
`v2` are accepted. The response includes an evidence ID, value or explicit
`UNKNOWN`, source, observation and sample timestamps, unit, and window. The
backend also exposes its own request counter and duration histogram at
`GET /metrics` for Prometheus scraping. See [monitoring](monitoring.md).

After `make argo-up`, `make rollout-up` and `make register-rollout`, an
authenticated viewer can call `GET /api/v1/workloads/{id}/analysis` on the
registered `checkout-canary` Rollout. It returns UID-scoped Rollout status
and bounded AnalysisRun phases, measurements, source and timestamps. The
read-only `get_rollout_analysis` tool uses the same lab identity. The current
investigation graph accepts only the original Deployment; the Rollout
workload response exposes `investigation_supported: false` until that path is
implemented. See [Argo](argo.md).

Validation: `make test-db` uses the separate `releasepilot_test` database and
the real guarded lab read. `make test` omits this opt-in suite. Run `make lint`
and `bash -n scripts/*.sh` as well. The database is not initialized by
application startup: missing migrations yield readiness failure. Local auth is
for a localhost lab; HTTPS, external identity and deployment hardening are
future work. `run_once` retains the M3 `ENGINE_NOT_CONFIGURED` refusal path for
regression tests; the worker entry point uses the graph path.
