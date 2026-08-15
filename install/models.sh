#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
MODEL_ROOT="$COMFY_DIR/models"

DIFFUSION_DIR="$MODEL_ROOT/diffusion_models"
LORA_DIR="$MODEL_ROOT/loras"
VAE_DIR="$MODEL_ROOT/vae"
TEXT_ENCODER_DIR="$MODEL_ROOT/text_encoders"

BASE_URL="https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files"
UNCENSORED_URL="https://huggingface.co/rzgar/Wan2.2_LightX2V_4Step_Uncensored/resolve/main"

banner

mkdir -p \
    "$DIFFUSION_DIR" \
    "$LORA_DIR" \
    "$VAE_DIR" \
    "$TEXT_ENCODER_DIR"

download_model() {
    local url="$1"
    local destination="$2"

    if [[ -f "$destination" ]]; then
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
# Official Wan 2.2 I2V 14B base models
########################################

download_model \
    "$BASE_URL/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" \
    "$DIFFUSION_DIR/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"

download_model \
    "$BASE_URL/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors" \
    "$DIFFUSION_DIR/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"

########################################
# Official Wan 2.2 VAE
########################################

download_model \
    "$BASE_URL/vae/wan_2.1_vae.safetensors" \
    "$VAE_DIR/wan_2.1_vae.safetensors"

########################################
# UMT5 XXL text encoder
########################################

download_model \
    "$BASE_URL/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    "$TEXT_ENCODER_DIR/umt5_xxl_fp8_e4m3fn_scaled.safetensors"

########################################
# Community unrestricted LightX2V LoRAs
########################################

download_model \
    "$UNCENSORED_URL/Wan2.2_LightX2V_high_n54vv.safetensors" \
    "$LORA_DIR/Wan2.2_LightX2V_high_n54vv.safetensors"

download_model \
    "$UNCENSORED_URL/Wan2.2_LightX2V_low_n54vv.safetensors" \
    "$LORA_DIR/Wan2.2_LightX2V_low_n54vv.safetensors"

echo
log_success "Wan 2.2 model installation complete."

echo
echo "Installed model files:"
find "$MODEL_ROOT" -type f -name "*.safetensors" -print | sort
