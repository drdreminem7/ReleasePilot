#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
state="$root/.releasepilot-lab"
env_file="$state/postgres.env"
container=releasepilot-m3-postgres
image=postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336

command -v docker >/dev/null || { echo 'Docker is required' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Docker daemon is unavailable' >&2; exit 1; }
mkdir -p "$state"
if [[ ! -f "$env_file" ]]; then
  umask 077
  printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > "$env_file"
fi
chmod 600 "$env_file"

if docker container inspect "$container" >/dev/null 2>&1; then
  label=$(docker container inspect "$container" --format '{{index .Config.Labels "releasepilot.dev/purpose"}}')
  [[ "$label" == m3-postgres ]] || { echo 'Container name collision; refusing to reuse' >&2; exit 1; }
  docker start "$container" >/dev/null
else
  docker volume create releasepilot-m3-pgdata >/dev/null
  docker run -d --name "$container" \
    --label releasepilot.dev/purpose=m3-postgres \
    --env-file "$env_file" \
    -e POSTGRES_USER=releasepilot -e POSTGRES_DB=releasepilot \
    -p 127.0.0.1:15432:5432 \
    -v releasepilot-m3-pgdata:/var/lib/postgresql \
    "$image" >/dev/null
fi

for attempt in {1..40}; do
  if docker exec "$container" pg_isready -U releasepilot -d releasepilot >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U releasepilot -d releasepilot >/dev/null || {
  echo 'ReleasePilot Postgres did not become ready' >&2
  exit 1
}

if ! docker exec "$container" psql -U releasepilot -d postgres -Atqc \
  "SELECT 1 FROM pg_database WHERE datname='releasepilot_test'" | rg -q '^1$'; then
  docker exec "$container" createdb -U releasepilot releasepilot_test
fi
printf 'ReleasePilot PostgreSQL ready on 127.0.0.1:15432; data volume retained.\n'

