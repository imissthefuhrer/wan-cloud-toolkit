#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PORT="${COMFY_PORT:-8888}"

# Model downloads are optional for launching the UI. Use --full to require
# all Wan workflow assets before starting.
VERIFY_ARGS=(--basic)
case "${1:-}" in
    "") ;;
    --full) VERIFY_ARGS=() ;;
    *) log_error "Usage: $0 [--full]"; exit 1 ;;
esac
if [[ $# -gt 1 ]]; then
    log_error "Usage: $0 [--full]"
    exit 1
fi

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
# Installation verification
########################################

log_info "Running installation verification..."
echo

"$SCRIPT_DIR/install/verify.sh" "${VERIFY_ARGS[@]}"

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
