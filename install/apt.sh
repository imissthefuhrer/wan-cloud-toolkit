#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

banner

########################################
# Privilege handling
########################################

if [[ "$EUID" -eq 0 ]]; then
    APT_PREFIX=()
    log_info "Running as root; sudo is not required."
else
    if ! command -v sudo >/dev/null 2>&1; then
        log_error "This script is not running as root and sudo is not installed."
        exit 1
    fi

    APT_PREFIX=(sudo)
    log_info "Running as non-root user; using sudo."
fi

########################################
# Operating system
########################################

log_info "Checking operating system..."

if ! grep -qi '^ID=ubuntu' /etc/os-release; then
    log_error "This toolkit currently supports Ubuntu only."
    exit 1
fi

log_success "Ubuntu detected."

########################################
# Required packages
########################################

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

########################################
# Update package lists
########################################

log_info "Updating package lists..."

"${APT_PREFIX[@]}" apt-get update

########################################
# Install packages
########################################

for pkg in "${PACKAGES[@]}"; do

    if dpkg -s "$pkg" >/dev/null 2>&1; then
        log_success "$pkg already installed."
    else
        log_info "Installing $pkg..."
        "${APT_PREFIX[@]}" apt-get install -y "$pkg"
    fi

done

log_success "System packages complete."
