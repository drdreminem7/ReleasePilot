# ReleasePilot

ReleasePilot is being built as a local Kubernetes release investigation and
safety portfolio project. M0–M3 pass their gates: a guarded Kubernetes lab,
sample workload, read-only inspection CLI, and a PostgreSQL backed API with
local authentication and a durable investigation queue. The LangGraph engine
has passed fixture tests against the lab; its live Gemini gate needs an API
key. M5 passes deterministic replay on six labeled synthetic cases, separate
from live-model performance. M6 passes live Prometheus, workload metrics and
traffic drills. M7 passes real Argo canary promotion and automatic abort,
with bounded AnalysisRun reads. The operator UI is a future milestone. See
[`PROGRESS.md`](PROGRESS.md) for observed milestone gates.

## Start

See [`docs/setup.md`](docs/setup.md). Run `make doctor`, `make setup`,
`make lint`, and `make test`. Then follow the [lab runbook](docs/lab.md) for
`make cluster-up`, `make sample-up`, fault injection and reset. `make doctor`
reports missing local prerequisites.
Use the [inspection runbook](docs/inspection.md) for read-only Deployment,
pod, event, log and ReplicaSet evidence.
Use the [API runbook](docs/api.md) to start the isolated database, migrate,
register the lab workload, create a local account and run the API and worker.
Use the [agent runbook](docs/agent.md) for the current graph and fault test.
Use the [evaluation runbook](docs/evaluation.md) for `make eval-replay`, its
evidence contracts, measured replay result and limitations.
Use the [monitoring runbook](docs/monitoring.md) for live scrape checks, traffic
phases, metric queries and the authenticated metrics API.
Use the [Argo runbook](docs/argo.md) for the guarded controller installation,
canary drill, reset and AnalysisRun evidence.

The architecture and safety contract are defined in
[`RELEASEPILOT_BUILD_SPEC.md`](RELEASEPILOT_BUILD_SPEC.md). All cluster writes
must target the dedicated `releasepilot-lab` k3d cluster after identity checks.

