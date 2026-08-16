#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
MODEL_ROOT="$COMFY_DIR/models"

DIFFUSION_DIR="$MODEL_ROOT/diffusion_models"
VAE_DIR="$MODEL_ROOT/vae"
TEXT_ENCODER_DIR="$MODEL_ROOT/text_encoders"
LORA_DIR="$MODEL_ROOT/loras"

REMIX_URL="https://huggingface.co/FX-FeiHou/wan2.2-Remix/resolve/main/NSFW"
UMT5_URL="https://huggingface.co/NSFW-API/NSFW-Wan-UMT5-XXL/resolve/main"

banner

mkdir -p \
    "$DIFFUSION_DIR" \
    "$VAE_DIR" \
    "$TEXT_ENCODER_DIR"     "$LORA_DIR"

download_model() {
    local url="$1"
    local destination="$2"

    if [[ -s "$destination" ]]; then
        log_success "Already exists: $(basename "$destination")"
        return 0
    fi

    log_info "Downloading: $(basename "$destination")"

    wget \
        --continue \
        --show-progress \
        -O "$destination" \
        "$url"

    if [[ ! -s "$destination" ]]; then
        log_error "Download failed: $destination"
        rm -f "$destination"
        exit 1
    fi

    log_success "Downloaded: $(basename "$destination")"
}

########################################
# Wan 2.2 Remix NSFW I2V 14B
########################################

download_model \
    "$REMIX_URL/Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors" \
    "$DIFFUSION_DIR/Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors"

download_model \
    "$REMIX_URL/Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors" \
    "$DIFFUSION_DIR/Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors"

########################################
# NSFW Wan UMT5-XXL
########################################

download_model \
    "$UMT5_URL/nsfw_wan_umt5-xxl_fp8_scaled.safetensors" \
    "$TEXT_ENCODER_DIR/nsfw_wan_umt5-xxl_fp8_scaled.safetensors"

########################################
# Wan 2.2 Lightning I2V LoRAs
########################################

LIGHTNING_URL="https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan22-Lightning"

download_model     "$LIGHTNING_URL/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors"     "$LORA_DIR/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors"

download_model     "$LIGHTNING_URL/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors"     "$LORA_DIR/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors"

########################################
# Wan VAE
########################################

VAE_URL="https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"

download_model \
    "$VAE_URL" \
    "$VAE_DIR/wan_2.1_vae.safetensors"

echo
log_success "Wan 2.2 Remix model installation complete."

echo
find "$MODEL_ROOT" \
    -type f \
    -name "*.safetensors" \
    -printf '%p\t%k KB\n' \
    | sort
