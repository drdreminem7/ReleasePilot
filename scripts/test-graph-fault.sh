#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cleanup() {
  status=$?
  trap - EXIT
  bash "$root/scripts/scenario-reset.sh" || status=1
  exit "$status"
}
trap cleanup EXIT
bash "$root/scripts/scenario-bad-image.sh"
bash "$root/scripts/scenario-verify-bad-image.sh"
cd "$root/backend"
RELEASEPILOT_TEST_FAULT=bad-image bash ../scripts/with-postgres.sh --test \
  .venv/bin/pytest -q tests/db/test_graph.py::test_fixture_graph_cites_real_bad_image_evidence
