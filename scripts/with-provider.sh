#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
key_file="$root/.releasepilot-lab/gemini.key"
if [[ -f "$key_file" ]]; then
  [[ ! -L "$key_file" ]] || { echo 'Gemini key file must not be a symlink' >&2; exit 1; }
  mode=$(stat -f %Lp "$key_file" 2>/dev/null || stat -c %a "$key_file")
  [[ "$mode" == 600 ]] || { echo 'Gemini key file must have mode 600' >&2; exit 1; }
  IFS= read -r GEMINI_API_KEY < "$key_file" || [[ -n "${GEMINI_API_KEY:-}" ]]
  [[ -n "${GEMINI_API_KEY:-}" ]] || { echo 'Gemini key file is empty' >&2; exit 1; }
  export GEMINI_API_KEY
fi
exec "$@"
