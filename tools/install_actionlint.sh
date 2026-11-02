#!/usr/bin/env bash
# Install a checksum-pinned validator into an explicitly supplied tool directory.
set -Eeuo pipefail
if (( $# != 1 )); then echo "Usage: $0 TOOL_DIRECTORY" >&2; exit 2; fi
if [[ "$(uname -s)/$(uname -m)" != Linux/x86_64 ]]; then
    echo "This installer supports Linux x86_64; install actionlint 1.7.12 for your platform." >&2
    exit 1
fi
archive=$(mktemp)
trap 'rm -f -- "$archive"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz \
    --output "$archive"
printf '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8  %s\n' "$archive" | sha256sum --check --status
mkdir -p "$1"
tar -xzf "$archive" -C "$1" actionlint
"$1/actionlint" -version
