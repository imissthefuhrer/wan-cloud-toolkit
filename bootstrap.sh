#!/usr/bin/env bash

set -Eeuo pipefail

echo "========================================="
echo " WAN Cloud Toolkit - Bootstrap"
echo "========================================="

fail() {
    echo
    echo "ERROR: $1"
    exit 1
}

echo
echo "[1/7] Checking privileges..."
[[ "$EUID" -eq 0 ]] || fail "Run this script as root."
echo "OK"

echo
echo "[2/7] Checking operating system..."
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "Ubuntu is required."
echo "Ubuntu ${VERSION_ID} detected"

echo
echo "[3/7] Checking NVIDIA GPU..."
command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi not found."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo "OK"

echo
echo "[4/7] Checking Python..."
command -v python3 >/dev/null 2>&1 || fail "Python 3 is required."
python3 --version
echo "OK"

echo
echo "[5/7] Checking PyTorch + CUDA..."
python3 - <<'PY'
import sys

try:
    import torch
except Exception as e:
    print(f"PyTorch import failed: {e}")
    sys.exit(1)

print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"PyTorch CUDA: {torch.version.cuda}")

if not torch.cuda.is_available():
    sys.exit("CUDA is not available to PyTorch.")

print(f"GPU: {torch.cuda.get_device_name(0)}")
print(
    f"VRAM: "
    f"{torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GB"
)
PY
echo "OK"

echo
echo "[6/7] Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
    ffmpeg \
    git \
    wget \
    curl \
    unzip \
    ca-certificates \
    build-essential

echo "OK"

echo
echo "[7/7] Creating application directories..."

mkdir -p \
    /workspace/wan-cloud-toolkit/models \
    /workspace/wan-cloud-toolkit/input \
    /workspace/wan-cloud-toolkit/output \
    /workspace/wan-cloud-toolkit/logs

echo "OK"

echo
echo "========================================="
echo " Bootstrap completed successfully"
echo "========================================="
echo
echo "GPU:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo
echo "PyTorch:"
python3 -c 'import torch; print(torch.__version__)'

echo
echo "FFmpeg:"
ffmpeg -version | head -n 1

echo
echo "Ready for ComfyUI installation."
