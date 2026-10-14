#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
subject=system:serviceaccount:releasepilot-lab:releasepilot-reader
allowed=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" auth can-i get pods --as="$subject")
secrets=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" auth can-i get secrets --as="$subject" || true)
patch=$(kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" auth can-i patch deployments --as="$subject" || true)
printf 'get pods=%s, get secrets=%s, patch deployments=%s\n' "$allowed" "$secrets" "$patch"
[[ "$allowed" == yes && "$secrets" == no && "$patch" == no ]] || rp_die "reader RBAC differs from least-privilege contract"

