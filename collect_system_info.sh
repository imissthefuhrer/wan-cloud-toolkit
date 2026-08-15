#!/usr/bin/env bash

set -u

echo "========================================="
echo " WAN Cloud Toolkit - System Information"
echo "========================================="

echo
echo "===== DATE ====="
date

echo
echo "===== OS ====="
cat /etc/os-release

echo
echo "===== KERNEL ====="
uname -a

echo
echo "===== CPU ====="
lscpu | grep -E 'Model name|CPU\(s\)|Thread|Core|Socket|NUMA' || true

echo
echo "===== MEMORY ====="
free -h

echo
echo "===== GPU ====="
nvidia-smi || true

echo
echo "===== NVIDIA DRIVER ====="
nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || true

echo
echo "===== CUDA TOOLKIT ====="
nvcc --version 2>/dev/null || echo "CUDA compiler (nvcc) not installed"

echo
echo "===== PYTHON ====="
python3 --version

echo
echo "===== PYTORCH ====="
python3 - <<'PY'
try:
    import torch

    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    print("PyTorch CUDA:", torch.version.cuda)

    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("VRAM:", round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2), "GB")
except Exception as e:
    print("PyTorch check failed:", e)
PY

echo
echo "===== PIP ====="
pip3 --version 2>/dev/null || true

echo
echo "===== GIT ====="
git --version 2>/dev/null || true

echo
echo "===== FFMPEG ====="
if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -version | head -n 2
else
    echo "FFmpeg: NOT INSTALLED"
fi

echo
echo "===== DISK ====="
df -h /workspace

echo
echo "===== WORKSPACE ====="
ls -ld /workspace
ls -la /workspace/wan-cloud-toolkit

echo
echo "===== NETWORK ====="
ip -brief address 2>/dev/null || true

echo
echo "========================================="
echo " Diagnostic complete"
echo "========================================="
