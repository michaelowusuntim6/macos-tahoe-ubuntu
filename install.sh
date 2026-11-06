#!/usr/bin/env bash
# macOS Tahoe Ubuntu — single entry point.
#
#   ./install.sh                     install using the recommended profile
#   ./install.sh --profile full      force a profile
#   ./install.sh --dry-run           show every change, change nothing
#   ./install.sh --offline           use bundled assets only
#   ./install.sh --resume            continue after an interruption
#   ./install.sh --restore           restore the pre-install desktop
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

readonly C_RESET=$'\033[0m' C_RED=$'\033[1;31m' C_YELLOW=$'\033[1;33m' C_DIM=$'\033[2m'

die() { printf '%sError:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
note() { printf '%s›%s %s\n' "$C_DIM" "$C_RESET" "$*"; }

on_error() {
    local rc=$? line=$1
    printf '\n%sInstallation failed%s (exit %d, line %d).\n' "$C_RED" "$C_RESET" "$rc" "$line" >&2
    printf 'The log is in %s/logs/.\n' "$ROOT" >&2
    printf 'If a phase was interrupted, fix the cause and run: ./install.sh --resume\n' >&2
    printf 'To return to the previous desktop: ./install.sh --restore\n' >&2
}
on_signal() {
    printf '\n%sInterrupted.%s Progress has been saved; resume with ./install.sh --resume\n' \
        "$C_YELLOW" "$C_RESET" >&2
    exit 130
}

trap 'on_error $LINENO' ERR
trap on_signal INT TERM HUP

usage() {
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
    case "$arg" in
        -h|--help) usage; exit 0 ;;
    esac
done

# ── bootstrap requirements ────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die \
    "python3 is required. Install it with: sudo apt install python3"
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
[[ "$PY_OK" == "1" ]] || die "Python 3.10 or newer is required (found $(python3 -V 2>&1))"

for cmd in gsettings dconf gnome-extensions; do
    command -v "$cmd" >/dev/null 2>&1 || die \
        "$cmd is required. This project targets an Ubuntu GNOME desktop."
done

[[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" || -S "/run/user/$(id -u)/bus" ]] || \
    die "no user D-Bus session found; run install.sh from a GNOME terminal session"

mkdir -p state logs backups reports
if command -v flock >/dev/null 2>&1; then
    exec 9>"state/.install.lock"
    flock -n 9 || die "another installation is already running"
fi

# ── run the engine ────────────────────────────────────────────────────────
note "macOS Tahoe Ubuntu — engine start"
set +e
python3 -E -s "$ROOT/engine/main.py" "$@"
rc=$?
set -e

if (( rc != 0 )); then
    printf '\n%sInstallation did not complete.%s\n' "$C_RED" "$C_RESET" >&2
    printf 'Logs: %s/logs/  •  State: %s/state/installation.json\n' "$ROOT" "$ROOT" >&2
    exit "$rc"
fi

if [[ " $* " != *" --verify "* && " $* " != *" --diagnostics "* && \
      " $* " != *" --dry-run "* && " $* " != *" --restore "* ]]; then
    note "Done. Log out and back in to activate the new GNOME Shell theme."
fi
