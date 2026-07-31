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
