#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PYTHON="$COMFY_DIR/venv/bin/python"
CUSTOM_NODES="$COMFY_DIR/custom_nodes"

# Full workflow verification is the default. --basic checks the installation
# while allowing ComfyUI to start before the large workflow models are present.
CHECK_MODELS=true
case "${1:-}" in
    "") ;;
    --basic) CHECK_MODELS=false ;;
    *) log_error "Usage: $0 [--basic]"; exit 1 ;;
esac
if [[ $# -gt 1 ]]; then
    log_error "Usage: $0 [--basic]"
    exit 1
fi

EXPECTED_COMFY_COMMIT="9a470e073e2742d4edd6e7ea1ce28d861a77d9c4"

banner

log_info "Running WAN 2.2 Remix environment verification..."

FAILURES=0

########################################
# Helper
########################################

check_pass() {
    log_success "$1"
}

check_fail() {
    log_error "$1"
    FAILURES=$((FAILURES + 1))
}

########################################
# Basic commands
########################################

echo
log_info "Checking required system commands..."

for cmd in git python3.11 wget curl ffmpeg tmux nvidia-smi; do
    if command -v "$cmd" >/dev/null 2>&1; then
        check_pass "$cmd available."
    else
        check_fail "$cmd not found."
    fi
done

########################################
# ComfyUI
########################################

echo
log_info "Checking ComfyUI..."

if [[ ! -d "$COMFY_DIR/.git" ]]; then
    check_fail "ComfyUI Git repository not found."
else
    check_pass "ComfyUI repository found."

    ACTUAL_COMFY_COMMIT="$(
        git -C "$COMFY_DIR" rev-parse HEAD
    )"

    if [[ "$ACTUAL_COMFY_COMMIT" == "$EXPECTED_COMFY_COMMIT" ]]; then
        check_pass "ComfyUI commit: $ACTUAL_COMFY_COMMIT"
    else
        check_fail \
            "Wrong ComfyUI commit. Expected $EXPECTED_COMFY_COMMIT, got $ACTUAL_COMFY_COMMIT"
    fi
fi

if [[ -f "$COMFY_DIR/main.py" ]]; then
    check_pass "ComfyUI main.py found."
else
    check_fail "ComfyUI main.py missing."
fi

########################################
# Python
########################################

echo
log_info "Checking Python..."

if command -v python3.11 >/dev/null 2>&1; then

    SYSTEM_PYTHON_VERSION="$(
        python3.11 -c \
        'import sys; print(".".join(map(str, sys.version_info[:3])))'
    )"

    check_pass "System Python: $SYSTEM_PYTHON_VERSION"

else
    check_fail "Python 3.11 not available."
fi

if [[ -x "$PYTHON" ]]; then

    VENV_PYTHON_VERSION="$(
        "$PYTHON" -c \
        'import sys; print(".".join(map(str, sys.version_info[:3])))'
    )"

    VENV_PYTHON_MAJOR_MINOR="$(
        "$PYTHON" -c \
        'import sys; print(".".join(map(str, sys.version_info[:2])))'
    )"

    if [[ "$VENV_PYTHON_MAJOR_MINOR" == "3.11" ]]; then
        check_pass "ComfyUI Python: $VENV_PYTHON_VERSION"
    else
        check_fail \
            "ComfyUI venv uses Python $VENV_PYTHON_VERSION instead of 3.11."
    fi

else
    check_fail "ComfyUI Python venv not found."
fi

########################################
# GPU
########################################

echo
log_info "Checking NVIDIA GPU..."

if command -v nvidia-smi >/dev/null 2>&1; then

    if ! nvidia-smi \
        --query-gpu=name,memory.total,driver_version \
        --format=csv,noheader; then
        check_fail "NVIDIA driver/GPU query failed."
    fi

else
    check_fail "nvidia-smi unavailable."
fi

########################################
# PyTorch / CUDA
########################################

echo
log_info "Checking PyTorch and CUDA..."

if [[ -x "$PYTHON" ]]; then

    if "$PYTHON" - <<'PY'
import sys
import torch
import torchvision
import torchaudio

EXPECTED_TORCH = "2.4.1+cu124"
EXPECTED_TORCHVISION = "0.19.1+cu124"
EXPECTED_TORCHAUDIO = "2.4.1+cu124"
EXPECTED_CUDA = "12.4"

errors = []

print(f"PyTorch:      {torch.__version__}")
print(f"Torchvision:  {torchvision.__version__}")
print(f"Torchaudio:   {torchaudio.__version__}")
print(f"CUDA runtime: {torch.version.cuda}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.__version__ != EXPECTED_TORCH:
    errors.append(
        f"PyTorch expected {EXPECTED_TORCH}, got {torch.__version__}"
    )

if torchvision.__version__ != EXPECTED_TORCHVISION:
    errors.append(
        f"Torchvision expected {EXPECTED_TORCHVISION}, got {torchvision.__version__}"
    )

if torchaudio.__version__ != EXPECTED_TORCHAUDIO:
    errors.append(
        f"Torchaudio expected {EXPECTED_TORCHAUDIO}, got {torchaudio.__version__}"
    )

if torch.version.cuda != EXPECTED_CUDA:
    errors.append(
        f"CUDA runtime expected {EXPECTED_CUDA}, got {torch.version.cuda}"
    )

if not torch.cuda.is_available():
    errors.append("CUDA is not available to PyTorch.")

if torch.cuda.is_available():

    gpu = torch.cuda.get_device_name(0)

    vram = (
        torch.cuda.get_device_properties(0).total_memory
        / (1024 ** 3)
    )

    print(f"GPU:          {gpu}")
    print(f"VRAM:         {vram:.1f} GB")

if errors:

    print()
    print("PyTorch verification FAILED:")

    for error in errors:
        print(f"  - {error}")

    sys.exit(1)

PY
    then
        check_pass "PyTorch/CUDA stack verified."
    else
        check_fail "PyTorch/CUDA verification failed."
    fi

else
    check_fail "ComfyUI Python executable not found."
fi

if [[ -x "$PYTHON" ]]; then
    if "$PYTHON" -m pip check; then
        check_pass "Python dependencies consistent."
    else
        check_fail "Python dependency conflicts detected."
    fi
fi

########################################
# SageAttention
########################################

echo
log_info "Checking SageAttention..."

if [[ -x "$PYTHON" ]]; then

    if "$PYTHON" -c "from sageattention import sageattn" >/dev/null 2>&1; then
        check_pass "SageAttention import verified."
    else
        check_fail "SageAttention is not installed or cannot be imported."
    fi

else
    check_fail "Cannot check SageAttention: ComfyUI Python executable not found."
fi

########################################
# Custom nodes
########################################

echo
log_info "Checking pinned custom nodes..."

declare -A EXPECTED_NODES=(
    ["ComfyUI-WanVideoWrapper"]="e926f7a0"
    ["ComfyUI-KJNodes"]="ffd4d1c908af896ed720d2edcd5cd151e5a06e70"
    ["ComfyUI-Easy-Use"]="a1b402b"
    ["ComfyUI-Custom-Scripts"]="aac13aa7ce35b07d43633c3bbe654a38c00d74f5"
    ["ComfyUI-Frame-Interpolation"]="a969c01dbccd9e5510641be04eb51fe93f6bfc3d"
)

for node in "${!EXPECTED_NODES[@]}"; do

    node_dir="$CUSTOM_NODES/$node"
    expected="${EXPECTED_NODES[$node]}"

    if [[ ! -d "$node_dir/.git" ]]; then
        check_fail "$node repository missing."
        continue
    fi

    actual="$(
        git -C "$node_dir" rev-parse HEAD
    )"

    if [[ "$actual" == "$expected" || \
          "${actual:0:${#expected}}" == "$expected" ]]; then

        check_pass "$node: $actual"

    else

        check_fail \
            "$node has wrong commit. Expected $expected, got $actual"

    fi

done

########################################
# Model files
########################################

if [[ "$CHECK_MODELS" == true ]]; then
    RIFE_MODEL=""
    if [[ -x "$PYTHON" && -f "$CUSTOM_NODES/ComfyUI-Frame-Interpolation/config.yaml" ]]; then
        if ! RIFE_MODEL="$("$PYTHON" - "$CUSTOM_NODES/ComfyUI-Frame-Interpolation" <<'PYTHON'
import os, sys, yaml
root = sys.argv[1]
with open(os.path.join(root, "config.yaml")) as f:
    config = yaml.safe_load(f)
print(os.path.abspath(os.path.join(root, config["ckpts_path"], "rife", "rife47.pth")))
PYTHON
    )"; then
            check_fail "Could not resolve the configured RIFE checkpoint path."
        fi
    else
        check_fail "Cannot resolve RIFE checkpoint: Python or node configuration missing."
    fi
    echo
    log_info "Checking Option B model files..."

    REQUIRED_MODELS=(
        "$COMFY_DIR/models/diffusion_models/Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors"
        "$COMFY_DIR/models/diffusion_models/Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors"
        "$COMFY_DIR/models/text_encoders/nsfw_wan_umt5-xxl_fp8_scaled.safetensors"
        "$COMFY_DIR/models/loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors"
        "$COMFY_DIR/models/loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors"
        "$COMFY_DIR/models/vae/wan_2.1_vae.safetensors"
        "$RIFE_MODEL"
    )

    for model in "${REQUIRED_MODELS[@]}"; do

        if [[ -s "$model" ]]; then

            size="$(
                du -h "$model" | cut -f1
            )"

            check_pass "$(basename "$model") [$size]"

        else

            check_fail "Missing model: $model"

        fi

    done
else
    log_info "Workflow model checks skipped (--basic)."
fi

########################################
# PyTorch constraint file
########################################

echo
log_info "Checking PyTorch constraint file..."

CONSTRAINTS_FILE="$COMFY_DIR/wan-cloud-constraints.txt"

if [[ -f "$CONSTRAINTS_FILE" ]]; then

    check_pass "Constraint file found."

    if grep -q '^torch==2\.4\.1+cu124$' "$CONSTRAINTS_FILE"; then
        check_pass "Torch constraint: 2.4.1"
    else
        check_fail "Torch constraint is incorrect."
    fi

    if grep -q '^torchvision==0\.19\.1+cu124$' "$CONSTRAINTS_FILE"; then
        check_pass "Torchvision constraint: 0.19.1"
    else
        check_fail "Torchvision constraint is incorrect."
    fi

    if grep -q '^torchaudio==2\.4\.1+cu124$' "$CONSTRAINTS_FILE"; then
        check_pass "Torchaudio constraint: 2.4.1"
    else
        check_fail "Torchaudio constraint is incorrect."
    fi

else

    check_fail "PyTorch constraint file missing."

fi

if [[ -x "$PYTHON" && -f "$CONSTRAINTS_FILE" ]]; then
    if "$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"; then
        check_pass "Protected CUDA dependency snapshot verified."
    else
        check_fail "Protected CUDA dependency snapshot mismatch."
    fi
fi

########################################
# Final result
########################################

if [[ -x "$PYTHON" ]]; then
    if "$PYTHON" "$SCRIPT_DIR/../tools/check_diffusers.py"; then
        check_pass "Pinned Python compatibility versions and wrapper diffusers imports verified."
    else
        check_fail "Python compatibility versions or wrapper diffusers imports failed."
    fi
fi

echo

if [[ "$FAILURES" -eq 0 ]]; then

    log_success "====================================="
    log_success " ALL WAN 2.2 CHECKS PASSED"
    log_success "====================================="

    echo
    echo "Environment:"
    echo "  ComfyUI:       0.3.45"
    echo "  Python:        3.11"
    echo "  PyTorch:       2.4.1+cu124"
    echo "  CUDA runtime:  12.4"
    echo "  Pipeline:      Wan 2.2 Remix I2V"
    echo
    echo "All pinned custom nodes verified."
    if [[ "$CHECK_MODELS" == true ]]; then
        echo "All required model files present (presence check only)."
    else
        echo "Basic installation verified; workflow models were not checked."
    fi
    echo "SageAttention verified."
    echo

else

    log_error "====================================="
    log_error " VERIFICATION FAILED"
    log_error "====================================="

    echo
    echo "Failures detected: $FAILURES"
    echo "Fix the failures above before starting ComfyUI."
    echo

    exit 1

fi
