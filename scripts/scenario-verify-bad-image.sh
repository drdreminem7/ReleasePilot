#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

for attempt in {1..30}; do
  pods=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get pods -l app=checkout-api -o json)
  observation=$(python3 -c '
import json, sys
for pod in json.load(sys.stdin)["items"]:
    for status in pod.get("status", {}).get("containerStatuses", []):
        waiting = status.get("state", {}).get("waiting", {})
        if waiting.get("reason") in ("ErrImagePull", "ImagePullBackOff"):
            print(pod["metadata"]["name"] + " " + waiting["reason"])
' <<< "$pods")
  if [[ -n "$observation" ]]; then
    pod_name=${observation%% *}
    events=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" get events --field-selector "involvedObject.name=$pod_name" -o json)
    if python3 -c '
import json, sys
events = json.load(sys.stdin)["items"]
matches = [e for e in events if "pull" in e.get("message", "").lower()]
if not matches:
    sys.exit(1)
print("Observed pod image pull failure event:", matches[-1]["reason"])
' <<< "$events"; then
      printf 'Observed pod state: %s\n' "$observation"
      exit 0
    fi
  fi
  sleep 2
done
rp_die "no bad-image pod state and matching Kubernetes event observed in 60 seconds"

