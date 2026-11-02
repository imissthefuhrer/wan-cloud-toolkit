#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ "${1:-}" == --run ]]; then
    set +e
    /opt/wan-cloud-toolkit/fast-start.sh 2>&1 | tee "$WAN_START_RUN_DIR/output.log"
    codes=("${PIPESTATUS[@]}")
    set -e
    printf 'command=%s tee=%s\n' "${codes[0]}" "${codes[1]}" > "$WAN_START_RUN_DIR/status"
    if (( codes[0] != 0 )); then exit "${codes[0]}"; fi
    exit "${codes[1]}"
fi
ROOT=/opt/wan-cloud-toolkit
# Never create log directories on an unconfirmed /workspace.
python3.11 - "$ROOT/tools" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from quick_check import mounted
mounted(Path('/workspace'), os.environ.get('WAN_VOLUME_ID', ''))
PY
mkdir -p "${COMFY_LOG_DIR:-/workspace/wan-cloud-logs}"
run_dir=$(mktemp -d "${COMFY_LOG_DIR:-/workspace/wan-cloud-logs}/fast-start-XXXXXXXX")
export WAN_START_RUN_DIR="$run_dir"
# Fixed session refuses duplicate startup. All failures retained, including quick checks.
tmux new-session -d -s wan-comfy -e "WAN_START_RUN_DIR=$run_dir" \
    -e "COMFY_DIR=${COMFY_DIR:-/workspace/ComfyUI}" \
    -e "COMFY_PORT=${COMFY_PORT:-8888}" \
    -e "COMFY_LOG_DIR=${COMFY_LOG_DIR:-/workspace/wan-cloud-logs}" \
    -e "COMFY_START_TIMEOUT=${COMFY_START_TIMEOUT:-300}" \
    -e "COMFY_PERFORMANCE=${COMFY_PERFORMANCE:-1}" \
    -e "WAN_VOLUME_ID=$WAN_VOLUME_ID" 'bash /opt/wan-cloud-toolkit/docker/autostart.sh --run'
printf 'Startup session: wan-comfy; logs: %s\n' "$run_dir"
