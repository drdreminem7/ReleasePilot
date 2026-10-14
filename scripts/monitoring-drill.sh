#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

sample_pid=
prometheus_pid=
cleanup() {
  status=$?
  trap - EXIT
  if [[ -n "$sample_pid" ]]; then
    kill "$sample_pid" 2>/dev/null || true
    wait "$sample_pid" 2>/dev/null || true
  fi
  if [[ -n "$prometheus_pid" ]]; then
    kill "$prometheus_pid" 2>/dev/null || true
    wait "$prometheus_pid" 2>/dev/null || true
  fi
  bash "$RP_ROOT/scripts/scenario-reset.sh" || status=1
  exit "$status"
}
trap cleanup EXIT

kubectl --context "$RP_CONTEXT" -n releasepilot port-forward service/releasepilot-prometheus 19090:9090 --address 127.0.0.1 >/tmp/releasepilot-prometheus-forward.log 2>&1 &
prometheus_pid=$!
ready=0
for attempt in {1..30}; do
  if curl -fsS --max-time 1 http://127.0.0.1:19090/-/ready >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || rp_die "Prometheus port-forward did not become ready"

start_sample_forward() {
  if [[ -n "$sample_pid" ]]; then
    kill "$sample_pid" 2>/dev/null || true
    wait "$sample_pid" 2>/dev/null || true
  fi
  kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" port-forward service/checkout-api 18080:8080 --address 127.0.0.1 >/tmp/releasepilot-sample-forward.log 2>&1 &
  sample_pid=$!
  local ready=0
  for attempt in {1..30}; do
    if curl -fsS --max-time 1 http://127.0.0.1:18080/ready >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  [[ "$ready" -eq 1 ]] || rp_die "sample port-forward did not become ready"
}

run_phase() {
  local phase=$1 mode=$2 traffic rate errors latency
  bash "$RP_ROOT/scripts/sample-mode.sh" "$mode"
  start_sample_forward
  traffic=$(python3 "$RP_ROOT/scripts/traffic.py" --duration 40 --rps 2)
  rate=$(cd "$RP_ROOT/backend" && .venv/bin/python -m releasepilot.prometheus_query request_rate)
  errors=$(cd "$RP_ROOT/backend" && .venv/bin/python -m releasepilot.prometheus_query error_ratio)
  latency=$(cd "$RP_ROOT/backend" && .venv/bin/python -m releasepilot.prometheus_query latency_p95)
  python3 - "$phase" "$traffic" "$rate" "$errors" "$latency" <<'PY'
import json
import sys

phase = sys.argv[1]
traffic, rate, errors, latency = (json.loads(raw) for raw in sys.argv[2:])
for item in (rate, errors, latency):
    assert item["state"] == "KNOWN", (phase, item)
    assert item["sample_at"] and item["source"] == "prometheus/releasepilot/checkout-api"
assert rate["value"] > 0, (phase, rate)
if phase == "baseline":
    assert traffic["http_200"] == 80 and traffic["http_503"] == 0, traffic
    assert errors["value"] <= 0.05 and latency["value"] < 0.1, (errors, latency)
elif phase == "errors":
    assert traffic["http_503"] == 80, traffic
    assert errors["value"] >= 0.8, errors
elif phase == "latency":
    assert traffic["http_200"] == 80 and traffic["http_503"] == 0, traffic
    assert latency["value"] >= 0.3 and errors["value"] <= 0.05, (latency, errors)
print(json.dumps({"phase": phase, "traffic": traffic, "request_rate": rate, "error_ratio": errors, "latency_p95": latency}, sort_keys=True))
PY
}

run_phase baseline healthy
run_phase errors error-heavy
run_phase latency latency-heavy
