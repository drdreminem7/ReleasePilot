#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" port-forward service/checkout-canary-stable 18082:8080 --address 127.0.0.1 >/tmp/releasepilot-stable-forward.log 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true; wait "$forward_pid" 2>/dev/null || true' EXIT
version=
for attempt in {1..30}; do
  response=$(curl -fsS --max-time 1 http://127.0.0.1:18082/version 2>/dev/null || true)
  if [[ -n "$response" ]]; then
    version=$(python3 -c 'import json,re,sys; d=json.loads(sys.argv[1]); v=d.get("version", ""); assert d.get("mode") == "healthy" and re.fullmatch(r"v[0-9]{1,12}", v); print(v)' "$response")
    break
  fi
  sleep 1
done
[[ -n "$version" ]] || rp_die "healthy stable Service was not reachable"
patch=$(python3 - "$version" <<'PY'
import json
import sys

version = sys.argv[1]
print(json.dumps([
    {"op": "replace", "path": "/spec/template/metadata/labels/version", "value": version},
    {"op": "replace", "path": "/spec/template/spec/containers/0/env/0/value", "value": "healthy"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/env/1/value", "value": version},
]))
PY
)
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" patch rollout checkout-canary --type=json -p "$patch"
ready=0
for attempt in {1..90}; do
  phase=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.phase}' 2>/dev/null || true)
  replicas=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get rollout checkout-canary -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
  if [[ "$phase" == Healthy && "$replicas" == 2 ]]; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || rp_die "Rollout did not return to a healthy stable revision"
printf 'Healthy stable Rollout restored at %s\n' "$version"
