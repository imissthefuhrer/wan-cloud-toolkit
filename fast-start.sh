#!/usr/bin/env bash
# Uses the existing launcher and its console/performance logging supervisor.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if (( $# )); then echo "Usage: $0" >&2; exit 1; fi
exec "$SCRIPT_DIR/start.sh" --quick
