#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" port-forward service/checkout-api 18080:8080 --address 127.0.0.1 >/tmp/releasepilot-port-forward.log 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
ready=0
for attempt in {1..20}; do
  if curl -fsS --max-time 1 http://127.0.0.1:18080/ready >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || rp_die "checkout-api never became ready through loopback port-forward"
curl -fsS --max-time 3 http://127.0.0.1:18080/health
printf '\n'
curl -fsS --max-time 3 http://127.0.0.1:18080/version
printf '\n'
curl -fsS --max-time 3 http://127.0.0.1:18080/checkout
printf '\n'
curl -fsS --max-time 3 http://127.0.0.1:18080/metrics | head -20

