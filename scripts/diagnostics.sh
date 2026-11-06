#!/usr/bin/env bash
# Write a diagnostics bundle (no automatic upload) and print its location.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 -E -s "$ROOT/engine/main.py" --diagnostics "$@"
