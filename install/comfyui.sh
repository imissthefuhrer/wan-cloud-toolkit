#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"

COMFY_REPO="https://github.com/Comfy-Org/ComfyUI.git"
COMFY_COMMIT="9a470e073e2742d4edd6e7ea1ce28d861a77d9c4"

PYTORCH_VERSION="2.4.1"
TORCHVISION_VERSION="0.19.1"
TORCHAUDIO_VERSION="2.4.1"

PYTORCH_INDEX="https://download.pytorch.org/whl/cu124"

banner

########################################
# Verify Python 3.11
########################################

if ! command -v python3.11 >/dev/null 2>&1; then
    log_error "Python 3.11 is required but was not found."
    exit 1
fi

PYTHON_VERSION="$(
    python3.11 -c \
    'import sys; print(".".join(map(str, sys.version_info[:3])))'
)"

PYTHON_MAJOR_MINOR="$(
    python3.11 -c \
    'import sys; print(".".join(map(str, sys.version_info[:2])))'
)"

if [[ "$PYTHON_MAJOR_MINOR" != "3.11" ]]; then
    log_error "Wrong Python version: $PYTHON_VERSION"
    log_error "Python 3.11 is required."
    exit 1
fi

log_success "Using Python $PYTHON_VERSION."

########################################
# Clone ComfyUI
########################################

if [[ -d "$COMFY_DIR/.git" ]]; then

    log_info "ComfyUI repository already exists."

else

    log_info "Cloning ComfyUI..."

    git clone \
        "$COMFY_REPO" \
        "$COMFY_DIR"

fi

########################################
# Fetch exact revision
########################################

log_info "Fetching ComfyUI tags..."

git -C "$COMFY_DIR" fetch --tags

log_info "Checking out ComfyUI 0.3.45..."

git -C "$COMFY_DIR" checkout --detach "$COMFY_COMMIT"

ACTUAL_COMMIT="$(git -C "$COMFY_DIR" rev-parse HEAD)"

if [[ "$ACTUAL_COMMIT" != "$COMFY_COMMIT" ]]; then

    log_error "ComfyUI commit verification failed."
    log_error "Expected: $COMFY_COMMIT"
    log_error "Actual:   $ACTUAL_COMMIT"

    exit 1

fi

log_success "ComfyUI pinned to 0.3.45."
log_success "Commit: $ACTUAL_COMMIT"

########################################
# Python virtual environment
########################################

if [[ ! -x "$COMFY_DIR/venv/bin/python" ]]; then

    log_info "Creating ComfyUI Python 3.11 virtual environment..."

    python3.11 -m venv "$COMFY_DIR/venv"

else

    log_success "ComfyUI virtual environment already exists."

fi

PYTHON="$COMFY_DIR/venv/bin/python"

########################################
# Verify venv Python
########################################

VENV_VERSION="$(
    "$PYTHON" -c \
    'import sys; print(".".join(map(str, sys.version_info[:3])))'
)"

VENV_MAJOR_MINOR="$(
    "$PYTHON" -c \
    'import sys; print(".".join(map(str, sys.version_info[:2])))'
)"

if [[ "$VENV_MAJOR_MINOR" != "3.11" ]]; then

    log_error "ComfyUI venv is using Python $VENV_VERSION."
    log_error "Python 3.11 is required."

    exit 1

fi

log_success "ComfyUI venv uses Python $VENV_VERSION."

########################################
# Upgrade packaging tools
########################################

log_info "Updating pip/setuptools/wheel..."

"$PYTHON" -m pip install \
    --upgrade \
    pip \
    setuptools \
    wheel

########################################
# Install exact PyTorch CUDA 12.4 stack
########################################

log_info "Installing pinned PyTorch CUDA 12.4 stack..."

"$PYTHON" -m pip install \
    --index-url "$PYTORCH_INDEX" \
    "torch==${PYTORCH_VERSION}" \
    "torchvision==${TORCHVISION_VERSION}" \
    "torchaudio==${TORCHAUDIO_VERSION}"

########################################
# Create dependency constraints
########################################

CONSTRAINTS_FILE="$COMFY_DIR/wan-cloud-constraints.txt"

cat > "$CONSTRAINTS_FILE" <<CONSTRAINTS
torch==${PYTORCH_VERSION}
torchvision==${TORCHVISION_VERSION}
torchaudio==${TORCHAUDIO_VERSION}
CONSTRAINTS

log_success "PyTorch constraints created."

########################################
# Install ComfyUI requirements
########################################

if [[ ! -f "$COMFY_DIR/requirements.txt" ]]; then

    log_error "ComfyUI requirements.txt not found."

    exit 1

fi

log_info "Installing ComfyUI 0.3.45 requirements..."

"$PYTHON" -m pip install \
    -r "$COMFY_DIR/requirements.txt" \
    -c "$CONSTRAINTS_FILE"

########################################
# Verify PyTorch
########################################

log_info "Verifying PyTorch/CUDA..."

"$PYTHON" - <<'PY'
import sys
import torch
import torchvision
import torchaudio

EXPECTED_TORCH = "2.4.1+cu124"
EXPECTED_TORCHVISION = "0.19.1+cu124"
EXPECTED_TORCHAUDIO = "2.4.1+cu124"

print(f"Python:       {sys.version.split()[0]}")
print(f"PyTorch:      {torch.__version__}")
print(f"Torchvision:  {torchvision.__version__}")
print(f"Torchaudio:   {torchaudio.__version__}")
print(f"CUDA runtime: {torch.version.cuda}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.__version__ != EXPECTED_TORCH:
    raise SystemExit(
        f"Wrong PyTorch version. Expected {EXPECTED_TORCH}, "
        f"got {torch.__version__}"
    )

if torchvision.__version__ != EXPECTED_TORCHVISION:
    raise SystemExit(
        f"Wrong torchvision version. Expected {EXPECTED_TORCHVISION}, "
        f"got {torchvision.__version__}"
    )

if torchaudio.__version__ != EXPECTED_TORCHAUDIO:
    raise SystemExit(
        f"Wrong torchaudio version. Expected {EXPECTED_TORCHAUDIO}, "
        f"got {torchaudio.__version__}"
    )

if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available to PyTorch.")

gpu = torch.cuda.get_device_name(0)

vram = (
    torch.cuda.get_device_properties(0).total_memory
    / (1024 ** 3)
)

print(f"GPU:          {gpu}")
print(f"VRAM:         {vram:.1f} GB")
PY

########################################
# Verify ComfyUI
########################################

if [[ ! -f "$COMFY_DIR/main.py" ]]; then

    log_error "ComfyUI installation appears incomplete."

    exit 1

fi

log_success "ComfyUI installation complete."

echo
echo "ComfyUI:"
echo "  Version: 0.3.45"
echo "  Commit:  $ACTUAL_COMMIT"
echo "  Path:    $COMFY_DIR"
echo "  Python:  $VENV_VERSION"
echo
echo "PyTorch:"
echo "  Version:    $PYTORCH_VERSION"
echo "  CUDA wheel: cu124"
echo "  Torchvision: $TORCHVISION_VERSION"
echo "  Torchaudio:  $TORCHAUDIO_VERSION"
echo
