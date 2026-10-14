# Developer setup (M0)

Requirements: macOS or Linux, Python 3.12 or 3.13, uv, Node.js 22+, npm,
Docker, k3d 5.9.0 and kubectl 1.32.x for M1. Reserve at least 4 GiB RAM for the initial
lab and more for later Prometheus/Argo profiles; this is a planning estimate,
not a measured peak. The lab is not exposed publicly by default.

Run `make doctor`, then `make setup`, `make lint` and `make test`. `make doctor`
exits nonzero when required tools or the Docker daemon are unavailable. Start
Docker Desktop (or an equivalent local daemon) before lab creation. No
Kubernetes context is needed for M0 setup. See [the lab runbook](lab.md) for
cluster creation, fault drills and reset. Cluster commands require the dedicated
`k3d-releasepilot-lab` context plus a node UID fingerprint captured at creation.

For M3, start the isolated PostgreSQL container with `make db-up`, then apply
`make db-migrate`. The container binds only to `127.0.0.1:15432` and stores
data in a dedicated Docker volume. The local password file is generated in
`.releasepilot-lab/postgres.env` with mode 0600 and is ignored by Git. The
developer machine's PostgreSQL instance is not used. See [the API runbook](api.md).

