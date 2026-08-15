#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"

WITH_MODELS=false

for arg in "$@"; do
    case "$arg" in
        --with-models)
            WITH_MODELS=true
            ;;
        *)
            log_error "Unknown option: $arg"
            echo
            echo "Usage:"
            echo "  ./bootstrap.sh"
            echo "  ./bootstrap.sh --with-models"
            exit 1
            ;;
    esac
done

banner

log_info "WAN Cloud Toolkit bootstrap starting..."

echo
log_info "Target ComfyUI directory: $COMFY_DIR"
echo

########################################
# System packages
########################################

log_info "Step 1/6: System packages"
"$SCRIPT_DIR/install/apt.sh"

########################################
# Python
########################################

log_info "Step 2/6: Python"
"$SCRIPT_DIR/install/python.sh"

########################################
# ComfyUI
########################################

log_info "Step 3/6: ComfyUI"
"$SCRIPT_DIR/install/comfyui.sh"

########################################
# Models
########################################

if [[ "$WITH_MODELS" == true ]]; then
    log_info "Step 4/6: Wan 2.2 models"
    "$SCRIPT_DIR/install/models.sh"
else
    log_warn "Step 4/6: Model installation skipped."
    log_warn "Run with --with-models to download Wan 2.2 models."
fi

########################################
# Nodes
########################################

log_info "Step 5/6: Node check"
"$SCRIPT_DIR/install/nodes.sh"

########################################
# Verification
########################################

if [[ "$WITH_MODELS" == true ]]; then
    log_info "Step 6/6: Verification"
    "$SCRIPT_DIR/install/verify.sh"
else
    log_info "Step 6/6: Verification skipped because models were not requested."
fi

echo
log_success "====================================="
log_success " BOOTSTRAP COMPLETE"
log_success "====================================="
echo

if [[ "$WITH_MODELS" == true ]]; then
    echo "Wan 2.2 models: installed"
else
    echo "Wan 2.2 models: NOT installed"
    echo
    echo "To install them:"
    echo "  ./install/models.sh"
fi

echo
echo "To start ComfyUI:"
echo "  ./start.sh"
echo
