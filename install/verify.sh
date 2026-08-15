#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"

banner

log_info "Running WAN Cloud Toolkit verification..."

########################################
# Basic commands
########################################

for cmd in git python3 wget curl ffmpeg; do
    require_command "$cmd"
done

########################################
# ComfyUI
########################################

if [[ ! -d "$COMFY_DIR" ]]; then
    log_error "ComfyUI not found: $COMFY_DIR"
    exit 1
fi

if [[ ! -f "$COMFY_DIR/main.py" ]]; then
    log_error "ComfyUI main.py not found."
    exit 1
fi

log_success "ComfyUI found."

########################################
# Python virtual environment
########################################

if [[ ! -f "$COMFY_DIR/venv/bin/python" ]]; then
    log_error "ComfyUI virtual environment not found."
    exit 1
fi

PYTHON="$COMFY_DIR/venv/bin/python"

log_success "ComfyUI virtual environment found."

########################################
# PyTorch / CUDA
########################################

"$PYTHON" - <<'PY'
import sys

try:
    import torch
except Exception as e:
    print(f"ERROR: Could not import PyTorch: {e}")
    sys.exit(1)

print(f"PyTorch: {torch.__version__}")
print(f"PyTorch CUDA: {torch.version.cuda}")
print(f"CUDA available: {torch.cuda.is_available()}")

if not torch.cuda.is_available():
    print("ERROR: CUDA is not available.")
    sys.exit(1)

gpu = torch.cuda.get_device_name(0)
vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)

print(f"GPU: {gpu}")
print(f"VRAM: {vram:.1f} GB")

if vram < 20:
    print("WARNING: Less than 20 GB VRAM detected.")
PY

log_success "PyTorch/CUDA verification complete."

########################################
# Required model files
########################################

REQUIRED_MODELS=(
    "$COMFY_DIR/models/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
    "$COMFY_DIR/models/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
    "$COMFY_DIR/models/vae/wan_2.1_vae.safetensors"
    "$COMFY_DIR/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    "$COMFY_DIR/models/loras/Wan2.2_LightX2V_high_n54vv.safetensors"
    "$COMFY_DIR/models/loras/Wan2.2_LightX2V_low_n54vv.safetensors"
)

echo
log_info "Checking Wan 2.2 model files..."

for model in "${REQUIRED_MODELS[@]}"; do
    if [[ -s "$model" ]]; then
        log_success "$(basename "$model")"
    else
        log_error "Missing model: $model"
        exit 1
    fi
done

########################################
# Summary
########################################

echo
log_success "====================================="
log_success " ALL WAN CLOUD CHECKS PASSED"
log_success "====================================="
echo

echo "ComfyUI: $COMFY_DIR"
echo "Python:  $PYTHON"
echo
echo "Wan 2.2 I2V:"
echo "  Official 14B FP8 base"
echo "  Community unrestricted LightX2V"
echo
