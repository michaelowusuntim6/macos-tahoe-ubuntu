#!/usr/bin/env bash
# Restore the machine-specific pre-install configuration.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 -E -s "$ROOT/engine/main.py" --restore "$@"
