#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

banner

########################################
# Python version
########################################

log_info "Checking Python..."

if ! command -v python3.11 >/dev/null 2>&1; then
    log_error "Python 3.11 is not installed."
    exit 1
fi

PYTHON_VERSION="$(
    python3.11 -c \
    'import sys; print(".".join(map(str, sys.version_info[:3])))'
)"

PYTHON_MAJOR_MINOR="$(
    python3.11 -c \
    'import sys; print(".".join(map(str, sys.version_info[:2])))'
)"

if [[ "$PYTHON_MAJOR_MINOR" != "3.11" ]]; then
    log_error "Wrong Python version detected: $PYTHON_VERSION"
    log_error "Python 3.11 is required."
    exit 1
fi

log_success "Python $PYTHON_VERSION detected."

########################################
# venv support
########################################

# Exercise venv creation and its bundled pip rather than checking --help or
# requiring a global pip installation for a non-default Ubuntu interpreter.
PROBE_DIR="$(mktemp -d)"
trap 'rm -rf -- "$PROBE_DIR"' EXIT
if ! python3.11 -m venv "$PROBE_DIR/venv"; then
    log_error "Python 3.11 venv support is not installed."
    exit 1
fi

log_success "Python 3.11 venv support available."

########################################
# pip
########################################

if ! "$PROBE_DIR/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    log_error "pip is not available in a Python 3.11 virtual environment."
    exit 1
fi

log_success "Python 3.11 venv pip available."

echo
log_success "Python environment check complete."
echo "Python: $(python3.11 --version)"
echo
