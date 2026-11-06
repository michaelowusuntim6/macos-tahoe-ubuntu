#!/usr/bin/env bash
# Build a portable release package in releases/.
#
#   ./export.sh                 write releases/macos-tahoe-ubuntu-v1.0.0.tar.gz
#   ./export.sh --output DIR    write the archive somewhere else
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
exec python3 -E -s "$ROOT/engine/exporter.py" "$@"
