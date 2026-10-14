#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set image deployment/checkout-api checkout-api=releasepilot/checkout-api:m1
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set env deployment/checkout-api CHECKOUT_MODE=healthy CHECKOUT_VERSION=v1
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" rollout status deployment/checkout-api --timeout=120s

