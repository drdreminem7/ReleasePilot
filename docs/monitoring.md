# Local monitoring (M6)

Complete the [lab setup](lab.md), including `make sample-up`, before running
`make monitoring-up`. Every monitoring script checks the active context,
dedicated k3d cluster name, node UID fingerprint and lab namespace before a
cluster operation. Prometheus runs in `releasepilot` with a six hour, ephemeral
TSDB and a ClusterIP Service. Its `checkout-api` target is the live sample
Service in `releasepilot-lab`. The `releasepilot-api` target is configured but
will remain down until the API is deployed in the cluster in M10; local
`make run-api` runs outside the cluster. A down target is not an API metric
value of zero.

Run `make monitoring-smoke` to port-forward Prometheus over loopback and
verify its live `checkout-api` scrape reports `up=1`. Run
`make monitoring-drill` to switch the sample through healthy, error-heavy,
and latency-heavy modes and send 80 requests at 2 requests per second in each
mode. The script asserts 200/503 responses and live Prometheus request rate,
error ratio and p95 latency, then resets the sample to healthy even on error.
It restarts the sample port-forward after every rollout because port-forward
binds to a particular pod. Do not interrupt the script during cleanup.

Prometheus scrapes every five seconds. Named rate and histogram queries use a
30-second lookback; a new Prometheus server needs at least two scrapes and a
new fault mode needs roughly 30 seconds of fresh traffic before its ratio or
p95 reflects the new mode. The drill sends traffic for 40 seconds before each
query and then evaluates the observed sample. These windows are part of the
test contract; changing them requires recalibrating assertions.

`PrometheusReader` accepts four metric names and `v1`/`v2` only. It renders
fixed PromQL templates; callers cannot supply PromQL or a URL. HTTP requests
have a three-second timeout, 32 KiB response limit and vector shape check.
No series, non-finite values and stale samples become `UNKNOWN` with a null
value and error code. Server errors fail closed. Every result includes source,
UTC observation time, sample time when available, unit and lookback window.
`scrape_up` is target availability and has no version label; the three workload
traffic metrics are version-tagged. The sample exposes
`checkout_requests_total{version,code}` and
`checkout_request_duration_seconds_bucket{version,le}` from the official
Prometheus Python client.

After `make db-up`, `make db-migrate` and `make register-lab`, the authenticated
API serves `GET /api/v1/workloads/{id}/metrics?metric=request_rate&version=v1`
to viewers and operators. It verifies the registered lab Deployment UID before
reading Prometheus. The API process exposes its own `/metrics` for the future
backend scrape target. Run `make test-monitoring-api` for an opt-in live API
test against the separate test database and guarded lab; it verifies
authentication, an observed scrape, a missing `v2` series as `UNKNOWN`, and
rejection of arbitrary metric names. `make test` runs unit tests without the
lab and `make test-db` checks the process exposition endpoint.

Prometheus data is ephemeral: restarting the pod loses historical samples and
rate queries return `UNKNOWN` until enough new samples exist. The drill's
traffic source is a local port-forward and is designed for this lab's one
sample replica, not a load benchmark. Version `v2` will be meaningful after
the rollout milestone. Grafana is omitted to keep the lab small.
