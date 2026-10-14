#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lab-guard.sh"

[[ "${CONFIRM_RELEASEPILOT_DELETE:-}" == "$RP_NAME" ]] || rp_die "set CONFIRM_RELEASEPILOT_DELETE=$RP_NAME to delete the lab"
rp_require_lab
k3d cluster delete "$RP_NAME"
rm -f "$RP_MARKER"
printf 'Deleted the verified dedicated lab.\n'

