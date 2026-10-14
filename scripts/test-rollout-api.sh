#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"
rp_require_lab
cd "$RP_ROOT/backend"
RELEASEPILOT_TEST_ROLLOUT=1 bash ../scripts/with-postgres.sh --test .venv/bin/pytest -q tests/db/test_rollout_api.py
