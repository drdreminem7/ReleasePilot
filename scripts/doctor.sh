#!/usr/bin/env bash
set -u

missing=0
printf 'OS/arch: %s/%s\n' "$(uname -s)" "$(uname -m)"
if [[ "$(uname -s)" == "Darwin" ]]; then
  memory_bytes=$(sysctl -n hw.memsize 2>/dev/null || true)
else
  memory_bytes=$(awk '/MemTotal:/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || true)
fi
if [[ -n "$memory_bytes" ]]; then
  printf 'RAM: %.1f GiB\n' "$(awk -v n="$memory_bytes" 'BEGIN {print n / 1073741824}')"
  if awk -v n="$memory_bytes" 'BEGIN {exit !(n < 4294967296)}'; then
    printf 'WARNING: less than 4 GiB RAM; local lab may not fit\n'
  fi
else
  printf 'RAM: unavailable (cannot assess lab capacity)\n'
fi

for tool in python3 uv node npm docker k3d kubectl; do
  if command -v "$tool" >/dev/null 2>&1; then
    case "$tool" in
      python3) version=$(python3 --version 2>&1) ;;
      uv) version=$(uv --version 2>&1) ;;
      node) version=$(node --version 2>&1) ;;
      npm) version=$(npm --version 2>&1) ;;
      docker) version=$(docker --version 2>&1) ;;
      k3d) version=$(k3d version 2>&1 | head -1) ;;
      kubectl) version=$(kubectl version --client=true --output=json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])' 2>/dev/null || echo unknown) ;;
    esac
    printf '%s: %s\n' "$tool" "$version"
  else
    printf '%s: MISSING\n' "$tool"
    missing=1
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
    printf 'Docker daemon: ready\n'
  else
    printf 'Docker daemon: unavailable\n'
    missing=1
  fi
fi

if command -v kubectl >/dev/null 2>&1; then
  context=$(kubectl config current-context 2>/dev/null || true)
  printf 'Kubernetes context: %s\n' "${context:-none}"
  if [[ "$context" == "k3d-releasepilot-lab" ]]; then
    fingerprint=$(kubectl --context "$context" get namespace releasepilot-lab -o jsonpath='{.metadata.annotations.releasepilot\.dev/cluster-uid}' 2>/dev/null || true)
    printf 'Lab fingerprint: %s\n' "${fingerprint:-absent}"
  else
    printf 'Lab fingerprint: not inspected (unexpected or absent context)\n'
  fi
fi

if [[ "$missing" -ne 0 ]]; then
  printf 'Readiness: BLOCKED; install missing tools or start Docker.\n'
  exit 1
fi
printf 'Readiness: developer tools and Docker available; lab identity still requires cluster guard.\n'
