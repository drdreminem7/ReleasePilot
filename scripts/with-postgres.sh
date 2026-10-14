#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
env_file="$root/.releasepilot-lab/postgres.env"
[[ -f "$env_file" ]] || { echo 'Run make db-up first' >&2; exit 1; }
source "$env_file"
database=releasepilot
if [[ "${1:-}" == --test ]]; then
  database=releasepilot_test
  shift
fi
export RELEASEPILOT_DATABASE_URL="postgresql+psycopg://releasepilot:${POSTGRES_PASSWORD}@127.0.0.1:15432/${database}"
unset POSTGRES_PASSWORD
exec "$@"

