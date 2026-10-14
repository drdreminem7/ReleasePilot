#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" apply -f "$RP_ROOT/deploy/monitoring/prometheus.yaml"
kubectl --context "$RP_CONTEXT" -n releasepilot rollout status deployment/releasepilot-prometheus --timeout=120s
