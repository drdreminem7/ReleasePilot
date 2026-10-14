#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
docker info >/dev/null 2>&1 || rp_die "local Docker daemon is unavailable"
docker build -t releasepilot/checkout-api:m1 "$RP_ROOT/sample-app"
k3d image import releasepilot/checkout-api:m1 -c "$RP_NAME"
rp_require_lab
kubectl --context "$RP_CONTEXT" apply -f "$RP_ROOT/deploy/sample-app/checkout.yaml"
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set image deployment/checkout-api checkout-api=releasepilot/checkout-api:m1
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set env deployment/checkout-api CHECKOUT_MODE=healthy CHECKOUT_VERSION=v1
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" rollout restart deployment/checkout-api
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" rollout status deployment/checkout-api --timeout=120s
workload_uid=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get deployment checkout-api -o jsonpath='{.metadata.uid}')
[[ "$workload_uid" =~ ^[a-f0-9-]{36}$ ]] || rp_die "deployed workload UID is invalid"
printf '%s\n' "$workload_uid" > "$RP_ROOT/.releasepilot-lab/checkout-api.uid"
chmod 600 "$RP_ROOT/.releasepilot-lab/checkout-api.uid"

