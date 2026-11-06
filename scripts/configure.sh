#!/usr/bin/env bash
# Re-apply desktop configuration idempotently (does not reinstall assets).
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec "$ROOT/install.sh" --resume "$@"
