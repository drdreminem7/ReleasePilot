# ADR 0002: isolated local PostgreSQL and a transactional investigation queue

Date: 2026-10-13. Status: accepted for the local lab.

The M3 database is a dedicated PostgreSQL 18 container with an isolated
volume, loopback port 15432, and a separate `releasepilot_test` database. A
generated password lives only in an ignored local file. This avoids touching
the developer machine's unrelated PostgreSQL service. Alembic owns schema
creation and revision checks; API startup does not call `create_all`.

Investigation creation writes the queued record, initial event, and audit row
in one database transaction. A unique `(requested_by, idempotency_key)`
constraint resolves concurrent duplicate submissions. The worker claims one
queued row with `FOR UPDATE SKIP LOCKED`, records the claim atomically, and can
recover a claim after a process interruption. Before M4 has a configured
graph/provider, it explicitly escalates with `ENGINE_NOT_CONFIGURED`; it does
not infer a diagnosis or mutate Kubernetes.

Local authentication uses Argon2 password hashes, a random bearer token with
only its digest stored, a fixed eight hour expiry, and explicit logout.
Workload creation through the API is intentionally absent: the local admin
registration command performs a guarded live identity read before writing
the registry. This narrows the API's cluster scope to the known lab workload.

Tradeoffs: the local API has no HTTPS or external identity, and the worker
polls every second. Deployment security and graph execution arrive in later
milestones. The current FastAPI TestClient emits an upstream Starlette
deprecation warning for HTTPX; tests still pass.
