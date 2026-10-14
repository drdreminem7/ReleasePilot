# M2 read-only inspection

The local CLI reads only the registered `releasepilot-lab/checkout-api`
Deployment and resources selected by its fixed label. `sample-up` records the
actual Deployment UID in an ignored local file. The CLI checks active context,
node UID fingerprint and namespace annotation before any read. A replaced
Deployment UID is an error until the workload is deliberately re-registered.

```bash
cd backend
.venv/bin/python -m releasepilot inspect status
.venv/bin/python -m releasepilot inspect pods
.venv/bin/python -m releasepilot inspect history
.venv/bin/python -m releasepilot inspect events --pod NAME_FROM_PODS
.venv/bin/python -m releasepilot inspect logs --pod NAME_FROM_PODS
```

Outputs are JSON with `ok`, source, observation time, resource UID/version,
bounded data, and truncation status. Logs are limited to the most recent hour,
50 lines and 8192 bytes; events are limited to 20 recent matching pod events.
The redactor covers common token/password assignments but cannot guarantee
removal of every secret pattern. Do not put real secrets in lab logs. The CLI
never reads Kubernetes Secret objects and never offers a raw selector or
arbitrary resource name.

Install and verify the *separate* namespaced reader identity:

```bash
make reader-rbac-up
make reader-rbac-verify
make test-cluster
```

The local CLI uses the already configured lab kubeconfig so it can verify the
cluster node UID. The ServiceAccount is for a future in-cluster worker; it has
get/list for selected read resources, pod log get, and no Secret or write
verbs. No ServiceAccount token is copied into the local CLI or repository.
Its authorization is checked using `kubectl auth can-i` impersonation.

`make test` runs SDK boundary tests without a cluster. `make test-cluster` is
opt-in and requires the registered local lab. The adapter has no Argo read
path yet because Argo CRDs are introduced in M7. There is no database-backed
registry yet; M3 will persist workload identity.

