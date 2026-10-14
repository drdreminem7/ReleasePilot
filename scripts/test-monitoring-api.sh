#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" -n releasepilot port-forward service/releasepilot-prometheus 19090:9090 --address 127.0.0.1 >/tmp/releasepilot-prometheus-forward.log 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
ready=0
for attempt in {1..30}; do
  if curl -fsS --max-time 1 http://127.0.0.1:19090/-/ready >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || rp_die "Prometheus did not become ready through loopback port-forward"
cd "$RP_ROOT/backend"
RELEASEPILOT_TEST_MONITORING=1 bash ../scripts/with-postgres.sh --test .venv/bin/pytest -q tests/db/test_monitoring_api.py
