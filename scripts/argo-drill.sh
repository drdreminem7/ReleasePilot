#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

preview_pid=
cleanup() {
  status=$?
  trap - EXIT
  if [[ -n "$preview_pid" ]]; then
    kill "$preview_pid" 2>/dev/null || true
    wait "$preview_pid" 2>/dev/null || true
  fi
  bash "$RP_ROOT/scripts/rollout-reset.sh" || status=1
  exit "$status"
}
trap cleanup EXIT

initial_phase=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.phase}')
[[ "$initial_phase" == Healthy ]] || rp_die "Rollout must start Healthy"
run_number=$(date +%s)
healthy_version="v$run_number"
bad_version="v$((run_number + 1))"

run_candidate() {
  local label=$1 mode=$2 version=$3 expected_status=$4 expected_phase=$5
  local patch selector stable traffic result
  patch=$(python3 - "$mode" "$version" <<'PY'
import json
import sys

mode, version = sys.argv[1:]
print(json.dumps([
    {"op": "replace", "path": "/spec/template/metadata/labels/version", "value": version},
    {"op": "replace", "path": "/spec/template/spec/containers/0/env/0/value", "value": mode},
    {"op": "replace", "path": "/spec/template/spec/containers/0/env/1/value", "value": version},
]))
PY
)
  kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" patch rollout checkout-canary --type=json -p "$patch"
  selector=
  for attempt in {1..90}; do
    selector=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get service checkout-canary-preview -o jsonpath='{.spec.selector.rollouts-pod-template-hash}' 2>/dev/null || true)
    stable=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.stableRS}' 2>/dev/null || true)
    if [[ -n "$selector" && "$selector" != "$stable" ]]; then
      break
    fi
    sleep 2
  done
  [[ -n "$selector" && "$selector" != "$stable" ]] || rp_die "candidate Service did not select a new ReplicaSet"
  kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" port-forward service/checkout-canary-preview 18081:8080 --address 127.0.0.1 >/tmp/releasepilot-preview-forward.log 2>&1 &
  preview_pid=$!
  local observed_version=
  for attempt in {1..30}; do
    result=$(curl -fsS --max-time 1 http://127.0.0.1:18081/version 2>/dev/null || true)
    if [[ -n "$result" ]]; then
      observed_version=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("version", ""))' "$result")
      [[ "$observed_version" == "$version" ]] && break
    fi
    sleep 1
  done
  [[ "$observed_version" == "$version" ]] || rp_die "preview Service did not serve $version"
  traffic=$(python3 "$RP_ROOT/scripts/traffic.py" --target canary --duration 35 --rps 3)
  python3 - "$traffic" "$expected_status" <<'PY'
import json
import sys

traffic = json.loads(sys.argv[1])
assert traffic["requests"] == 105, traffic
assert traffic[f"http_{sys.argv[2]}"] == 105, traffic
print(json.dumps(traffic, sort_keys=True))
PY
  kill "$preview_pid" 2>/dev/null || true
  wait "$preview_pid" 2>/dev/null || true
  preview_pid=
  local observed_phase=
  for attempt in {1..60}; do
    observed_phase=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.phase}' 2>/dev/null || true)
    if [[ "$observed_phase" == "$expected_phase" ]]; then
      break
    fi
    sleep 2
  done
  [[ "$observed_phase" == "$expected_phase" ]] || rp_die "$label Rollout phase $observed_phase, expected $expected_phase"
  local analysis expected_run_phase
  analysis=$(cd "$RP_ROOT/backend" && .venv/bin/python -m releasepilot.rollout_inspection analysis)
  expected_run_phase=Successful
  [[ "$label" != bad ]] || expected_run_phase=Failed
  python3 - "$analysis" "$expected_run_phase" "$label" <<'PY'
import json
import sys

evidence = json.loads(sys.argv[1])
assert evidence["source"] == "analysisruns/releasepilot-lab/checkout-canary"
assert evidence["observed_at"] and evidence["resource_uid"]
runs = evidence["data"]
assert runs, evidence
latest = max(runs, key=lambda item: item["started_at"] or "")
assert latest["phase"] == sys.argv[2], latest
assert latest["metrics"] and any(metric["measurements"] for metric in latest["metrics"])
print(json.dumps({"phase": sys.argv[3], "analysis_run": latest}, sort_keys=True))
PY
}

run_candidate healthy healthy "$healthy_version" 200 Healthy
run_candidate bad error-heavy "$bad_version" 503 Degraded
