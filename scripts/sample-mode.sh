#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
mode=${1:-}
case "$mode" in
  healthy|error-heavy|latency-heavy|readiness-failing) ;;
  *) rp_die "mode must be healthy, error-heavy, latency-heavy, or readiness-failing" ;;
esac
rp_require_lab
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set env deployment/checkout-api "CHECKOUT_MODE=$mode"
if [[ "$mode" == "readiness-failing" ]]; then
  printf 'Readiness-failing revision requested; its rollout is expected to remain unavailable.\n'
else
  kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" rollout status deployment/checkout-api --timeout=120s
fi

