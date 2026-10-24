#!/usr/bin/env bash

set -Eeuo pipefail

########################################
# Colors
########################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

########################################
# Logging
########################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[ OK ]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

########################################
# Check command exists
########################################

require_command() {

    if ! command -v "$1" >/dev/null 2>&1; then
        log_error "$1 is not installed."
        exit 1
    fi

}

# Combine Python compatibility pins with the existing protected CUDA snapshot.
# Never add non-CUDA pins to, or regenerate, the protected snapshot as a repair.
use_wan_constraints() {
    local protected="$1" root combined
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    combined="$(dirname "$protected")/wan-cloud-pip-constraints.txt"
    (umask 077; cat "$protected" "$root/constraints/wan-python.txt" > "$combined")
    export PIP_CONSTRAINT="$combined"
}

########################################
# Run command safely
########################################

run() {

    log_info "$*"

    "$@"

}

########################################
# Download file if missing
########################################

download_if_missing() {

    local url="$1"
    local file="$2"

    if [[ -f "$file" ]]; then
        log_success "$file already exists."
        return
    fi

    wget -O "$file" "$url"

}

########################################
# Banner
########################################

banner() {

cat << EOF

=====================================
      WAN CLOUD TOOLKIT
=====================================

EOF

}

########################################
# Verified Hugging Face LFS downloads
########################################

# Resolve authoritative LFS metadata before trusting an existing file. Keep
# interrupted transfers under .part and publish only a verified complete file.
download_model() {
    local url="$1" destination="$2"
    local metadata expected_sha expected_size partial="${2}.part"
    local toolkit_root
    toolkit_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    metadata="$(python3 "$toolkit_root/tools/model_metadata.py" "$url")" || return 1
    read -r expected_sha expected_size <<< "$metadata"

    if model_matches "$destination" "$expected_size" "$expected_sha"; then
        log_success "Verified existing model: $(basename "$destination")"
        return 0
    fi
    mkdir -p "$(dirname "$destination")"
    if [[ -e "$destination" ]]; then
        log_warn "Incomplete or corrupt model: $destination"
        if [[ ! -e "$partial" ]]; then
            mv -- "$destination" "$partial"
        else
            rm -- "$destination"
        fi
    fi
    # A full-length corrupt file cannot be repaired by resuming at its end.
    if [[ -f "$partial" ]] && [[ "$(stat -c %s "$partial")" -ge "$expected_size" ]]; then
        if model_matches "$partial" "$expected_size" "$expected_sha"; then
            mv -- "$partial" "$destination"
            return 0
        fi
        rm -- "$partial"
    fi
    log_info "Downloading: $(basename "$destination")"
    if ! wget --continue --show-progress -O "$partial" "$url"; then
        log_error "Transfer interrupted; rerun to resume $partial"
        return 1
    fi
    if ! model_matches "$partial" "$expected_size" "$expected_sha"; then
        log_error "Model size or SHA-256 mismatch: $partial; removing corrupt transfer."
        rm -f -- "$partial"
        return 1
    fi
    mv -- "$partial" "$destination"
    log_success "Downloaded and SHA-256 verified: $(basename "$destination")"
}

model_matches() {
    local file="$1" expected_size="$2" expected_sha="$3"
    [[ -f "$file" ]] || return 1
    [[ "$(stat -c %s "$file")" == "$expected_size" ]] || return 1
    printf '%s  %s\n' "$expected_sha" "$file" | sha256sum --check --status
}
