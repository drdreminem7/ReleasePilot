#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab

version=v1.10.1
base="https://github.com/argoproj/argo-rollouts/releases/download/$version"
work=$(mktemp -d "${TMPDIR:-/tmp}/releasepilot-argo.XXXXXX")
trap 'rm -rf "$work"' EXIT
curl -fsSL --max-time 90 "$base/install.yaml" -o "$work/install.yaml"
curl -fsSL --max-time 90 "$base/namespace-install.yaml" -o "$work/namespace-install.yaml"
printf '%s  %s\n' '149148429a6f8258b789003ffb9bc6698a526d611ecb1b185624217cf51bae7f' "$work/install.yaml" | shasum -a 256 -c -
printf '%s  %s\n' '4351d54af7aa295b5335ada1ba6d3ee9d93314fa78d72961acb8e38fb5dc9721' "$work/namespace-install.yaml" | shasum -a 256 -c -
"$RP_ROOT/backend/.venv/bin/python" "$RP_ROOT/scripts/extract-argo-crds.py" "$work/install.yaml" > "$work/crds.yaml"

kubectl --context "$RP_CONTEXT" apply --server-side -f "$work/crds.yaml"
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" apply -f "$work/namespace-install.yaml"
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set image deployment/argo-rollouts argo-rollouts=quay.io/argoproj/argo-rollouts:v1.10.1@sha256:fbcc4cf0a29da25d86230992b1dfdeadf30b6f1baa74ea7c9c98e3e580769396
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" set resources deployment/argo-rollouts --containers=argo-rollouts --requests=cpu=100m,memory=128Mi --limits=cpu=500m,memory=512Mi,ephemeral-storage=1Gi
kubectl --context "$RP_CONTEXT" -n "$RP_NAMESPACE" rollout status deployment/argo-rollouts --timeout=180s
kubectl --context "$RP_CONTEXT" wait --for=condition=Established --timeout=90s crd/rollouts.argoproj.io crd/analysisruns.argoproj.io crd/analysistemplates.argoproj.io
