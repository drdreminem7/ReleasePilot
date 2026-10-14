# M1 local lab runbook

This creates **only** a k3d cluster named `releasepilot-lab`. It changes the
local kubeconfig current context to `k3d-releasepilot-lab` after creation.
The script refuses to adopt an existing cluster without its locally recorded
node UID and matching namespace annotation. It does not inspect or change any
other cluster. Keep `.releasepilot-lab/cluster-uid` private and local.

```bash
make doctor
make cluster-up
make sample-up
make sample-smoke
```

After M2, `sample-up` also records the Deployment UID for the read-only
[inspection CLI](inspection.md). The UID file is ignored by Git.

`sample-smoke` uses loopback port 18080 and verifies `/ready`, `/health`,
`/version`, `/checkout` and `/metrics`. The API is only a ClusterIP service;
no public ingress is installed. A single checkout pod requests 25m CPU/32Mi
and is limited to 250m CPU/96Mi. The image has no ServiceAccount token,
runs as a non-root UID and uses a read-only root filesystem.

Bad image drill and restoration:

```bash
make scenario-bad-image
make scenario-verify-bad-image
make scenario-reset
make sample-smoke
```

The bad image uses the reserved `.invalid` domain. The verify script checks a
pod waiting reason plus a matching real Kubernetes event. The previous ready
replica may continue serving during this failed rolling update; do not equate
service availability with a successful rollout. `scenario-reset` restores the
healthy image and mode, then waits for rollout completion.

Other deterministic modes:

```bash
make sample-mode MODE=error-heavy       # /checkout returns 503
make sample-mode MODE=latency-heavy     # /checkout sleeps about 400 ms
make sample-mode MODE=readiness-failing # /ready returns 503; rollout cannot complete
make scenario-reset
```

View observed workload state after the guard check:

```bash
bash -c 'source scripts/lab-guard.sh; rp_require_lab; kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get pods'
```

`cluster-down` is destructive and **opt-in**. It requires the current named
context, the recorded node UID, the namespace annotation and the explicit
environment variable below. It removes only the named k3d cluster:

```bash
CONFIRM_RELEASEPILOT_DELETE=releasepilot-lab make cluster-down
```

If the local fingerprint file is lost, these scripts refuse all mutations,
including teardown. Inspect the cluster manually before any recovery. Do not
copy a fingerprint from an unrelated cluster. Docker, k3d, and sufficient disk
space are required. Later monitoring and Argo profiles need more memory than
this single pod lab.

