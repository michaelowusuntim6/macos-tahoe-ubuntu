#!/usr/bin/env bash
# Remove only the components owned by this project.
#
#   ./uninstall.sh            ask for confirmation, then restore the pre-install state
#   ./uninstall.sh --dry-run  show what would be removed
#   ./uninstall.sh --yes      no prompt (for automation)
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

dry=0
assume_yes=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry=1 ;;
        --yes|-y) assume_yes=1 ;;
        -h|--help)
            sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
    esac
done

latest="$(find "$ROOT/backups" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort | tail -1 || true)"
if [[ -z "$latest" ]]; then
    printf 'No backup exists. Refusing to remove components because the original\n' >&2
    printf 'configuration could not be restored. Nothing was changed.\n' >&2
    exit 1
fi

printf 'This will restore settings from:\n  %s\n' "$latest"
if (( ! assume_yes && ! dry )); then
    read -r -p "Remove the macOS Tahoe customization and restore the previous desktop? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }
fi

exec python3 -E -s "$ROOT/engine/main.py" --uninstall "$@"
