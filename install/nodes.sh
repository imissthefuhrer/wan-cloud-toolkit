#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"

banner

log_info "Checking native ComfyUI Wan 2.2 support..."

if [[ ! -f "$COMFY_DIR/main.py" ]]; then
    log_error "ComfyUI is not installed."
    exit 1
fi

if [[ ! -d "$COMFY_DIR/comfy" ]]; then
    log_error "ComfyUI core directory not found."
    exit 1
fi

log_success "ComfyUI core detected."

log_info "No third-party custom nodes required for the baseline Wan 2.2 workflow."

log_success "Node check complete."
