#!/usr/bin/env bash
# Verify the installed desktop. Adds --headless to also run an isolated
# nested GNOME Shell test (no logout required).
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
exec python3 -E -s "$ROOT/engine/main.py" --verify "$@"
