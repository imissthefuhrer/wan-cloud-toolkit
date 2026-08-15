#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PORT="${COMFY_PORT:-8888}"

banner

if [[ ! -d "$COMFY_DIR" ]]; then
    log_error "ComfyUI not found at $COMFY_DIR"
    log_error "Run ./bootstrap.sh first."
    exit 1
fi

PYTHON="$COMFY_DIR/venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    log_error "ComfyUI Python environment not found."
    exit 1
fi

log_info "Checking GPU before starting ComfyUI..."

"$PYTHON" - <<'PY'
import torch

if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available.")

gpu = torch.cuda.get_device_name(0)
vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)

print(f"GPU: {gpu}")
print(f"VRAM: {vram:.1f} GB")
print(f"PyTorch: {torch.__version__}")
print(f"CUDA: {torch.version.cuda}")
PY

echo
log_info "Starting ComfyUI..."
log_info "Listening on 0.0.0.0:${PORT}"
log_info "SSH tunnel target: 127.0.0.1:${PORT}"
echo

cd "$COMFY_DIR"

exec "$PYTHON" main.py \
    --listen 0.0.0.0 \
    --port "$PORT"
