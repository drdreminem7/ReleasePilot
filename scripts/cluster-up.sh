#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"

command -v k3d >/dev/null || rp_die "k3d is required"
command -v kubectl >/dev/null || rp_die "kubectl is required"
docker info >/dev/null 2>&1 || rp_die "local Docker daemon is unavailable"

if k3d cluster list -o json | python3 -c 'import json,sys; sys.exit(0 if any(c["name"] == "releasepilot-lab" for c in json.load(sys.stdin)) else 1)'; then
  rp_require_lab
  printf 'Existing dedicated lab verified.\n'
  exit 0
fi

[[ ! -e "$RP_MARKER" ]] || rp_die "stale local fingerprint exists; refusing to overwrite it"
printf 'Creating dedicated k3d cluster %s; existing contexts are not targeted.\n' "$RP_NAME"
k3d cluster create --config "$RP_ROOT/deploy/k3d/cluster.yaml"
kubectl config use-context "$RP_CONTEXT" >/dev/null
current=$(kubectl config current-context)
[[ "$current" == "$RP_CONTEXT" ]] || rp_die "created context was not selected"
uid=$(kubectl --context "$RP_CONTEXT" get node k3d-releasepilot-lab-server-0 -o jsonpath='{.metadata.uid}')
[[ "$uid" =~ ^[a-f0-9-]{36}$ ]] || rp_die "created node UID is invalid"
mkdir -p "$(dirname "$RP_MARKER")"
printf '%s\n' "$uid" > "$RP_MARKER"
chmod 600 "$RP_MARKER"
for namespace in releasepilot releasepilot-lab; do
  kubectl --context "$RP_CONTEXT" create namespace "$namespace"
  kubectl --context "$RP_CONTEXT" annotate namespace "$namespace" "releasepilot.dev/cluster-uid=$uid"
done
rp_require_lab
printf 'Dedicated lab ready.\n'

