#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

banner

log_info "Installing ComfyUI..."

if [[ -d "$COMFY_DIR/.git" ]]; then
    log_success "ComfyUI repository already exists at $COMFY_DIR"
else
    log_info "Cloning ComfyUI..."
    git clone https://github.com/Comfy-Org/ComfyUI.git "$COMFY_DIR"
fi

cd "$COMFY_DIR"

if [[ ! -d "venv" ]]; then
    log_info "Creating ComfyUI Python virtual environment..."
    "$PYTHON_BIN" -m venv venv
fi

source venv/bin/activate

log_info "Upgrading pip..."
python -m pip install --upgrade pip

log_info "Installing PyTorch CUDA 13.0..."

pip install \
    torch \
    torchvision \
    torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu130

log_info "Installing ComfyUI requirements..."

pip install -r requirements.txt

log_success "ComfyUI installation complete."

echo
echo "ComfyUI directory:"
echo "$COMFY_DIR"

echo
echo "Python:"
python --version

echo
echo "PyTorch:"
python -c 'import torch; print(torch.__version__)'

echo
echo "CUDA:"
python -c 'import torch; print(torch.cuda.is_available())'

echo
echo "GPU:"
python -c 'import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE")'
