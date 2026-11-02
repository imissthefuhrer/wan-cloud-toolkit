#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if ! command -v actionlint >/dev/null 2>&1; then
    echo 'actionlint is required. Install 1.7.12 with tools/install_actionlint.sh TOOL_DIRECTORY and add it to PATH.' >&2
    exit 1
fi
exec actionlint .github/workflows/*.yml
