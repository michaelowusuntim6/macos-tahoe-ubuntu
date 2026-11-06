#!/usr/bin/env bash
# Diagnose managed components and re-apply anything that drifted.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
exec python3 -E -s "$ROOT/engine/main.py" --repair "$@"
