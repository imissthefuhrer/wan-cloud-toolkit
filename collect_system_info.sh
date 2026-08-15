#!/usr/bin/env bash

set -Eeuo pipefail

echo "========================================="
echo "WAN Cloud Toolkit - System Information"
echo "========================================="

echo
echo "===== OS ====="
cat /etc/os-release

echo
echo "===== Kernel ====="
uname -a

echo
echo "===== GPU ====="
nvidia-smi || true

echo
echo "===== CUDA ====="
nvcc --version || echo "CUDA Toolkit not installed"

echo
echo "===== Python ====="
python3 --version

echo
echo "===== Pip ====="
pip3 --version

echo
echo "===== Git ====="
git --version

echo
echo "===== FFmpeg ====="
ffmpeg -version | head -n 2 || echo "FFmpeg not installed"

echo
echo "===== Disk ====="
df -h

echo
echo "===== Memory ====="
free -h

echo
echo "===== CPU ====="
lscpu
