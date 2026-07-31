#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

banner

log_info "Checking operating system..."

if ! grep -qi ubuntu /etc/os-release; then
    log_error "This toolkit currently supports Ubuntu only."
    exit 1
fi

log_success "Ubuntu detected."

PACKAGES=(
    git
    wget
    curl
    unzip
    ffmpeg
    python3
    python3-venv
    python3-pip
    build-essential
)

log_info "Updating package lists..."
sudo apt-get update

for pkg in "${PACKAGES[@]}"; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        log_success "$pkg already installed."
    else
        log_info "Installing $pkg..."
        sudo apt-get install -y "$pkg"
    fi
done

log_success "System packages complete."
