#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" apply -f "$RP_ROOT/deploy/argo-rollouts/checkout-rollout.yaml"
kubectl --context "$RP_CONTEXT" apply -f "$RP_ROOT/deploy/monitoring/prometheus.yaml"
kubectl --context "$RP_CONTEXT" -n releasepilot rollout restart deployment/releasepilot-prometheus
kubectl --context "$RP_CONTEXT" -n releasepilot rollout status deployment/releasepilot-prometheus --timeout=120s

ready=0
for attempt in {1..90}; do
  replicas=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
  phase=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.phase}' 2>/dev/null || true)
  if [[ "$replicas" == 2 && "$phase" == Healthy ]]; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || rp_die "initial checkout-canary Rollout did not become healthy"
uid=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.metadata.uid}')
[[ "$uid" =~ ^[a-f0-9-]{36}$ ]] || rp_die "Rollout UID is missing or malformed"
printf '%s\n' "$uid" > "$RP_ROOT/.releasepilot-lab/checkout-canary.uid"
printf 'Healthy Rollout %s with UID %s\n' checkout-canary "$uid"
