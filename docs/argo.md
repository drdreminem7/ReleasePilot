# Argo progressive delivery in the local lab (M7)

Run `make cluster-up`, `make sample-up`, and `make monitoring-up` first. Then
run `make argo-up`, `make rollout-up`, and `make register-rollout`. Every script
checks the active `k3d-releasepilot-lab` context, the saved node UID and the
lab namespace fingerprint before touching Kubernetes. `argo-up` downloads
Argo Rollouts v1.10.1 release artifacts, verifies their published SHA-256
checksums, extracts only the five CRDs, and installs the official
namespace-scoped controller in `releasepilot-lab`. The controller image is
replaced with an immutable digest and CPU/memory limits. No Argo dashboard
or public Service is installed.

`checkout-canary` is a second instance of the same checkout sample image.
The original `checkout-api` Deployment remains for the M1–M6 fault and graph
tests. The Rollout starts with two healthy replicas, a stable Service, a
preview Service and an ordinary Service. Argo manages hash selectors for
the stable and preview Services. With no traffic router, `setWeight: 50` is
a **replica-count approximation**. The drill sends traffic directly to the
preview Service to obtain candidate-specific measurements. No claim of an
exact 50% split on the ordinary Service is made.

The `checkout-canary-safety` AnalysisTemplate queries the actual local
Prometheus service for the candidate version's 5xx ratio and p95 latency.
Thresholds are 20% error ratio and 300 ms p95. Empty/non-finite series are
not treated as healthy: the metric cannot satisfy the success condition and
the run is inconclusive or failed. The Rollout pauses for 45 seconds before
inline analysis. The drill sends 105 requests over 35 seconds to the preview
Service, letting a 30-second Prometheus rate window fill before two 5-second
measurements. Prometheus scrapes every five seconds. If a metric fails,
Argo's controller aborts the candidate independently of ReleasePilot or a
Gemini model.

Run `make argo-drill` from a healthy Rollout. It promotes a healthy candidate,
then injects an error-heavy candidate and asserts that Argo marks the latest
AnalysisRun `Failed` and the Rollout `Degraded`. A guarded exit trap restores
the stable healthy revision, preserving AnalysisRun history. Candidate version
labels are unique numeric `v...` values per run, so repeated drills create
new revisions. `make rollout-reset` can be used separately. If the sample
image is rebuilt under the local `m1` tag, run `make rollout-refresh-image`
while the Rollout is healthy; it replaces pods one at a time after the guarded
image import.

The sample's `/metrics` response closes its HTTP connection. This matters
because a persistent Prometheus connection to the preview Service can remain
on the previous pod after Argo changes Service endpoints. The first healthy
M7 trial exposed this: Argo received empty candidate vectors and marked its
AnalysisRun `Inconclusive`. After closing scrape connections, the live rerun
recorded two successful healthy-candidate measurements (error ratio 0, p95
47.5 ms), promoted it, and then failed the error-heavy candidate at error
ratio 1.0. The stable Service served the healthy promoted version when the
reset ran.

Run `make test-rollout-api` after the drill to verify an authenticated viewer
can retrieve the Rollout UID, status and bounded AnalysisRun evidence through
`GET /api/v1/workloads/{id}/analysis`. `get_rollout_analysis` is also a
read-only catalog tool. Both check the registered Rollout UID. The current
investigation graph and fixed M6 metric endpoint still support the original
Deployment; Rollout diagnosis and action proposals follow in later phases.
The M4 live Gemini gate remains blocked until a key is supplied.

Argo AnalysisRuns are retained in this lab while the Rollout exists. The
monitoring TSDB is ephemeral. Recreating the Rollout changes its UID and
requires explicit re-registration; stale registrations fail closed. The
official namespace controller Role includes permissions needed by Argo in
`releasepilot-lab` (including its notification Secret), while ReleasePilot's
read-only graph does not receive that ServiceAccount or Secret data.
