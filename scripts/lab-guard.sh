#!/usr/bin/env bash
# Source from a script before any Kubernetes-changing command.
set -euo pipefail

RP_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RP_NAME=releasepilot-lab
RP_CONTEXT=k3d-releasepilot-lab
RP_NAMESPACE=releasepilot-lab
RP_MARKER="$RP_ROOT/.releasepilot-lab/cluster-uid"

rp_die() {
  printf 'ReleasePilot lab guard: %s\n' "$*" >&2
  exit 1
}

rp_require_lab() {
  [[ -f "$RP_MARKER" ]] || rp_die "missing local fingerprint at $RP_MARKER"
  local expected current actual annotation
  expected=$(cat "$RP_MARKER")
  [[ "$expected" =~ ^[a-f0-9-]{36}$ ]] || rp_die "invalid stored fingerprint"
  current=$(kubectl config current-context 2>/dev/null || true)
  [[ "$current" == "$RP_CONTEXT" ]] || rp_die "active context is '${current:-none}', expected $RP_CONTEXT"
  actual=$(kubectl --context "$RP_CONTEXT" get node k3d-releasepilot-lab-server-0 -o jsonpath='{.metadata.uid}' 2>/dev/null) || rp_die "cannot read dedicated lab node"
  [[ "$actual" == "$expected" ]] || rp_die "node UID fingerprint mismatch"
  annotation=$(kubectl --context "$RP_CONTEXT" get namespace "$RP_NAMESPACE" -o jsonpath='{.metadata.annotations.releasepilot\.dev/cluster-uid}' 2>/dev/null) || rp_die "cannot read lab namespace"
  [[ "$annotation" == "$expected" ]] || rp_die "namespace fingerprint mismatch"
  printf 'Verified %s (%s)\n' "$RP_CONTEXT" "$expected" >&2
}

