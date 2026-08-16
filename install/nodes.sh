#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
CUSTOM_NODES="$COMFY_DIR/custom_nodes"
PYTHON="$COMFY_DIR/venv/bin/python"

banner

if [[ ! -d "$COMFY_DIR" ]]; then
    log_error "ComfyUI not found at $COMFY_DIR"
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    log_error "ComfyUI Python environment not found."
    exit 1
fi

mkdir -p "$CUSTOM_NODES"

########################################
# Install exact custom-node revisions
########################################

install_node_repo() {
    local name="$1"
    local url="$2"
    local revision="$3"
    local dir="$CUSTOM_NODES/$name"

    if [[ -d "$dir/.git" ]]; then
        log_info "$name repository already exists."
    else
        log_info "Cloning $name..."
        git clone "$url" "$dir"
    fi

    git -C "$dir" fetch --all --tags

    log_info "Checking out $name revision $revision..."

    git -C "$dir" checkout --detach "$revision"

    log_success "$name pinned to $(git -C "$dir" rev-parse --short HEAD)."
}

########################################
# Versions matching supplied workflow
########################################

install_node_repo \
    "ComfyUI-WanVideoWrapper" \
    "https://github.com/kijai/ComfyUI-WanVideoWrapper.git" \
    "e926f7a0"

install_node_repo \
    "ComfyUI-KJNodes" \
    "https://github.com/kijai/ComfyUI-KJNodes.git" \
    "89dc2f8"

install_node_repo \
    "ComfyUI-Easy-Use" \
    "https://github.com/yolain/ComfyUI-Easy-Use.git" \
    "a1b402b"

install_node_repo \
    "ComfyUI-Custom-Scripts" \
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git" \
    "aac13aa7ce35b07d43633c3bbe654a38c00d74f5"

install_node_repo \
    "ComfyUI-Frame-Interpolation" \
    "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git" \
    "a969c01dbccd9e5510641be04eb51fe93f6bfc3d"

########################################
# Install Python requirements
########################################

install_requirements() {
    local name="$1"
    local requirements="$CUSTOM_NODES/$name/requirements.txt"

    if [[ -f "$requirements" ]]; then
        log_info "Installing requirements for $name..."

        "$PYTHON" -m pip install -r "$requirements"

        log_success "$name requirements installed."
    else
        log_info "$name has no requirements.txt; skipping."
    fi
}

install_requirements "ComfyUI-WanVideoWrapper"
install_requirements "ComfyUI-KJNodes"
install_requirements "ComfyUI-Easy-Use"
install_requirements "ComfyUI-Custom-Scripts"
install_requirements "ComfyUI-Frame-Interpolation"

########################################
# RIFE 4.7 model
########################################

VFI_MODELS="$CUSTOM_NODES/ComfyUI-Frame-Interpolation/models"
mkdir -p "$VFI_MODELS"

RIFE_MODEL="$VFI_MODELS/rife47.pth"

if [[ -s "$RIFE_MODEL" ]]; then

    log_success "rife47.pth already exists."

else

    log_info "Downloading RIFE 4.7 model..."

    wget \
        --continue \
        --show-progress \
        -O "$RIFE_MODEL" \
        "https://huggingface.co/marduk191/rife/resolve/main/rife47.pth"

    if [[ ! -s "$RIFE_MODEL" ]]; then
        log_error "RIFE model download failed."
        rm -f "$RIFE_MODEL"
        exit 1
    fi

    log_success "RIFE 4.7 model installed."

fi

########################################
# Summary
########################################

echo
log_success "Custom node installation complete."

echo
echo "Pinned custom nodes:"

for node in \
    ComfyUI-WanVideoWrapper \
    ComfyUI-KJNodes \
    ComfyUI-Easy-Use \
    ComfyUI-Custom-Scripts \
    ComfyUI-Frame-Interpolation
do

    printf "  %-35s %s\n" \
        "$node" \
        "$(git -C "$CUSTOM_NODES/$node" rev-parse --short HEAD)"

done

echo
echo "RIFE model:"
ls -lh "$RIFE_MODEL"
