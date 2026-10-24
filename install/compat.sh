#!/usr/bin/env bash
# Targeted Python-package repair; no Git checkouts, model downloads, or CUDA work.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"
COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PYTHON="$COMFY_DIR/venv/bin/python"
CONSTRAINTS_FILE="$COMFY_DIR/wan-cloud-constraints.txt"
[[ -x "$PYTHON" && -f "$CONSTRAINTS_FILE" ]] || {
    log_error "Existing venv and protected CUDA snapshot are required; refusing an unprotected repair."
    exit 1
}
"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
"$PYTHON" "$SCRIPT_DIR/../tools/check_diffusers.py" --requirements-only
use_wan_constraints "$CONSTRAINTS_FILE"
"$PYTHON" -m pip install --dry-run -c "$PIP_CONSTRAINT" -r "$SCRIPT_DIR/../constraints/wan-python.txt"
"$PYTHON" -m pip install -c "$PIP_CONSTRAINT" -r "$SCRIPT_DIR/../constraints/wan-python.txt"
"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
"$PYTHON" -m pip check
"$PYTHON" "$SCRIPT_DIR/../tools/check_diffusers.py"
