#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

banner

log_info "Checking Python..."

require_command python3

PYTHON_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"

log_info "Python ${PYTHON_VERSION} detected."

if ! python3 -m venv --help >/dev/null 2>&1; then
    log_error "Python venv support is not installed."
    exit 1
fi

log_success "Python venv support available."

log_success "Python environment check complete."
