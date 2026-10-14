#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
phase=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.phase}')
[[ "$phase" == Healthy ]] || rp_die "refusing image refresh while Rollout is not Healthy"
pods=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get pods -l app=checkout-canary -o jsonpath='{.items[*].metadata.name}')
[[ -n "$pods" ]] || rp_die "Rollout has no pods"
for pod in $pods; do
  kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" delete pod "$pod" --wait=true
  ready=0
  for attempt in {1..60}; do
    count=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
    if [[ "$count" == 2 ]]; then
      ready=1
      break
    fi
    sleep 2
  done
  [[ "$ready" -eq 1 ]] || rp_die "Rollout did not recover two ready pods after $pod"
done
printf 'Rollout pods refreshed from the locally imported image\n'
