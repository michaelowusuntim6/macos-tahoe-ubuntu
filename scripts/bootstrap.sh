#!/usr/bin/env bash
# Lightweight prerequisite check used by install.sh and tests.
# It does not change the system; install.sh performs the real bootstrap.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
fail=0
for cmd in python3 gsettings dconf gnome-extensions; do
    if command -v "$cmd" >/dev/null 2>&1; then
        printf 'ok   %s\n' "$cmd"
    else
        printf 'MISS %s\n' "$cmd"; fail=1
    fi
done
python3 - <<'PY' || fail=1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
[[ -f "$ROOT/config/desktop.json" ]] || { echo "MISS config/desktop.json"; fail=1; }
[[ -f "$ROOT/engine/main.py" ]] || { echo "MISS engine/main.py"; fail=1; }
exit "$fail"
