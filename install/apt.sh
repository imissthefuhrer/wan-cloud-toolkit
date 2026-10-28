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
    ca-certificates
    tmux
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

# Ubuntu's default python3 is not necessarily 3.11. Preserve an existing
# template-supplied 3.11 if it can create a complete virtual environment.
if ! command -v python3.11 >/dev/null 2>&1 || \
   ! python3.11 -c 'import venv, ensurepip' >/dev/null 2>&1 || \
   ! dpkg-query -W -f='${Status}' python3.11-dev 2>/dev/null | grep -qx 'install ok installed'; then
    NEED_PPA=false
    for package in python3.11 python3.11-venv python3.11-dev; do
        if ! apt-cache policy "$package" | grep -Eq 'Candidate: [0-9]'; then
            NEED_PPA=true
        fi
    done
    if [[ "$NEED_PPA" == true ]]; then
        # Deadsnakes publishes signed Python packages for these Ubuntu releases.
        # Do not silently configure an unsupported distribution.
        . /etc/os-release
        case "$VERSION_ID" in
            22.04|24.04) ;;
            *)
                log_error "Python 3.11 packages unavailable for Ubuntu $VERSION_ID. Use a RunPod template providing Python 3.11 and venv support."
                exit 1
                ;;
        esac
        "${APT_PREFIX[@]}" apt-get install -y software-properties-common
        "${APT_PREFIX[@]}" add-apt-repository -y ppa:deadsnakes/ppa
        "${APT_PREFIX[@]}" apt-get update
    fi
    "${APT_PREFIX[@]}" apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

log_success "System packages complete."
