#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set image deployment/checkout-api checkout-api=invalid.invalid/releasepilot/checkout-api:missing-m1
printf 'Bad image set. Inspect pods/events; rollout is expected to be unhealthy.\n'

