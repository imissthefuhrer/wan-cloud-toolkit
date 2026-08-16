#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PORT="${COMFY_PORT:-8888}"

banner

########################################
# Basic checks
########################################

if [[ ! -d "$COMFY_DIR" ]]; then
    log_error "ComfyUI not found at $COMFY_DIR"
    log_error "Run ./bootstrap.sh first."
    exit 1
fi

PYTHON="$COMFY_DIR/venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    log_error "ComfyUI Python environment not found."
    log_error "Run ./bootstrap.sh first."
    exit 1
fi

########################################
# Full environment verification
########################################

log_info "Running full environment verification..."
echo

"$SCRIPT_DIR/install/verify.sh"

echo
log_success "Environment verification passed."

########################################
# Start ComfyUI
########################################

echo
log_info "Starting ComfyUI..."
log_info "ComfyUI directory: $COMFY_DIR"
log_info "Listening on:      0.0.0.0:${PORT}"
log_info "RunPod proxy port: ${PORT}"
echo

cd "$COMFY_DIR"

exec "$PYTHON" main.py \
    --listen 0.0.0.0 \
    --port "$PORT"
