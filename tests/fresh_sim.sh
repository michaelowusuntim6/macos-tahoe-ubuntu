#!/usr/bin/env bash
# Simulate a fresh Ubuntu installation without touching the live desktop.
#
# Exports the portable release, extracts it into a temporary directory, and
# runs the offline installer with a private HOME, XDG dirs and D-Bus session.
# The live GNOME configuration is never modified.
#
#   tests/fresh_sim.sh            run the simulation
#   tests/fresh_sim.sh --keep     keep the temporary tree for inspection
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

command -v dbus-run-session >/dev/null || { echo "dbus-run-session is required"; exit 1; }

SIM="$(mktemp -d /tmp/tahoe-fresh-sim.XXXXXX)"
cleanup() {
    if (( KEEP )); then echo "simulation tree kept: $SIM"; else rm -rf "$SIM"; fi
}
trap cleanup EXIT

mkdir -p "$SIM"/{release,home,config,data,cache,run}
chmod 700 "$SIM/run"

echo "==> exporting portable release"
python3 -E -s "$ROOT/engine/exporter.py" --output "$SIM/release" >"$SIM/export.log" 2>&1
ARCHIVE="$(find "$SIM/release" -name '*.tar.gz' | head -1)"
[[ -n "$ARCHIVE" ]] || { echo "export produced no archive"; cat "$SIM/export.log"; exit 1; }
tar -xzf "$ARCHIVE" -C "$SIM"
PROJ="$(find "$SIM" -maxdepth 1 -type d -name 'macos-tahoe-ubuntu-v*' | head -1)"
[[ -d "$PROJ" ]] || { echo "extracted project missing"; exit 1; }

REAL_HOME="$HOME"
export SIM HOME="$SIM/home" XDG_CONFIG_HOME="$SIM/config" \
       XDG_DATA_HOME="$SIM/data" XDG_CACHE_HOME="$SIM/cache" \
       XDG_RUNTIME_DIR="$SIM/run"
export WAYLAND_DISPLAY="" DISPLAY=""

echo "==> first installation (offline, lightweight)"
if ! dbus-run-session -- bash -c "cd '$PROJ' && ./install.sh --offline --profile lightweight"; then
    echo "fresh installation FAILED"
    echo "simulation tree: $SIM"
    KEEP=1
    exit 1
fi

echo "==> second installation (idempotency)"
if ! dbus-run-session -- bash -c "cd '$PROJ' && ./install.sh --offline --profile lightweight"; then
    echo "second installation FAILED"
    KEEP=1
    exit 1
fi

echo "==> checking installed artefacts in the simulated HOME"
fail=0
check() { [[ -e "$1" ]] || { echo "MISSING: $1"; fail=1; }; }
check "$SIM/data/themes/TPCT-Mac-Dark/gnome-shell/gnome-shell.css"
check "$SIM/data/themes/TPCT-Mac-Light/gnome-shell/gnome-shell.css"
check "$SIM/data/icons/WhiteSur-dark/index.theme"
check "$SIM/data/icons/WhiteSur-light/index.theme"
check "$SIM/data/icons/WhiteSur-cursors/cursors/default"
check "$SIM/data/fonts/Inter-Variable.ttf"
check "$SIM/data/backgrounds/macos-tahoe/tahoe-dark.jpg"
check "$SIM/config/gtk-4.0/gtk.css"
check "$SIM/config/gtk-3.0/gtk.css"
check "$SIM/config/rofi/tahoe-dark.rasi"
check "$SIM/home/.local/bin/tahoe-spotlight"
check "$SIM/data/gnome-shell/extensions/tpct-mac-shell@tpct/metadata.json"
check "$SIM/data/gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com/metadata.json"
check "$PROJ/runtime/rofi/usr/bin/rofi"
check "$PROJ/reports/verification.json"
check "$PROJ/docs/reports/INSTALLATION_REPORT.md"
check "$SIM/data/macos-tahoe-ubuntu/appearance/appearance.json"
check "$SIM/config/autostart/tahoe-appearance.desktop"
check "$SIM/data/gnome-shell/extensions/macos-dock@vinnytherobot.github.io/metadata.json"
check "$SIM/data/gnome-shell/extensions/blur-my-shell@aunetx/metadata.json"
check "$SIM/data/themes/TPCT-Mac-Dark/gnome-shell/gnome-shell.css"

echo "==> checking simulated dconf state"
SETTINGS="$(dbus-run-session -- bash -c "gsettings get org.gnome.desktop.interface gtk-theme; gsettings get org.gnome.shell.extensions.dash-to-dock dock-position; gsettings get org.gnome.desktop.wm.preferences button-layout")"
echo "$SETTINGS"
grep -q "TPCT-Mac-Dark" <<<"$SETTINGS" || { echo "GTK theme not applied in simulation"; fail=1; }
grep -q "BOTTOM" <<<"$SETTINGS" || { echo "dock not moved to bottom"; fail=1; }
grep -q "close,minimize,maximize" <<<"$SETTINGS" || { echo "window buttons not applied"; fail=1; }

echo "==> checking for duplicate extension entries"
DUPES="$(dbus-run-session -- bash -c "gsettings get org.gnome.shell enabled-extensions")"
echo "$DUPES"
python3 - "$DUPES" <<'PY'
import ast, sys
items = ast.literal_eval(sys.argv[1])
if len(items) != len(set(items)):
    raise SystemExit("duplicate extensions after second install")
print(f"{len(items)} enabled extensions, no duplicates")
PY

echo "==> checking single-dock guard"
DISABLED="$(dbus-run-session -- bash -c "gsettings get org.gnome.shell disabled-extensions")"
echo "$DISABLED"
grep -q "ubuntu-dock@ubuntu.com" <<<"$DISABLED" || { echo "Ubuntu Dock is not blacklisted"; fail=1; }
grep -q "macos-dock@vinnytherobot.github.io" <<<"$DUPES" || { echo "MacOSDock is not enabled"; fail=1; }

echo "==> checking machine isolation"
if grep -q "$REAL_HOME/.config" "$SIM/config/gtk-3.0/gtk.css" 2>/dev/null; then
    echo "simulated file references the real HOME"; fail=1
fi

if (( fail )); then
    echo "FRESH-INSTALL SIMULATION FAILED"
    KEEP=1
    exit 1
fi
echo "FRESH-INSTALL SIMULATION PASSED"
