#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
kubectl --context "$RP_CONTEXT" apply -f "$RP_ROOT/deploy/rbac/reader.yaml"

