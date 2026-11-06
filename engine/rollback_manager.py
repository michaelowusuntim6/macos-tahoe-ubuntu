"""Rollback and uninstall: only touch what this project owns."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import app_manager, backup_manager, extension_manager, theme_manager
from . import utilities as u
from .state_manager import State

log = logging.getLogger("engine")

OWNED_PATHS = [
    "~/.local/share/themes/TPCT-Mac-Dark",
    "~/.local/share/themes/TPCT-Mac-Light",
    "~/.local/share/icons/WhiteSur-dark",
    "~/.local/share/icons/WhiteSur-light",
    "~/.local/share/icons/WhiteSur-cursors",
    "~/.local/share/fonts/Inter-Variable.ttf",
    "~/.local/share/backgrounds/macos-tahoe",
    "~/.local/share/gnome-shell/extensions/tpct-mac-shell@tpct",
    "~/.local/share/gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com",
    "~/.local/share/gnome-shell/extensions/blur-my-shell@aunetx",
    "~/.local/share/gnome-shell/extensions/macos-dock@vinnytherobot.github.io",
    "~/.local/share/macos-tahoe-ubuntu",
    "~/.local/bin/tahoe-appearance-follow",
    "~/.config/autostart/tahoe-appearance.desktop",
    "~/.config/tpct-mac",
    "~/.config/gtk-4.0/gtk.css",
    "~/.config/gtk-4.0/gtk-dark.css",
    "~/.config/rofi/tahoe-dark.rasi",
    "~/.config/rofi/tahoe-light.rasi",
    "~/.local/bin/tahoe-spotlight",
]


def restore_managed_settings(state: State, *, dry_run: bool = False) -> list[str]:
    """Put every GSettings key we changed back to its pre-install value."""
    restored: list[str] = []
    entries = state.settings.get("settings", {})
    for ident, entry in list(entries.items()):
        schema, key = entry["schema"], entry["key"]
        schemadir = Path(entry["schemadir"]) if entry.get("schemadir") else None
        if schemadir and not schemadir.exists():
            schemadir = None
        before = entry.get("before")
        if dry_run:
            restored.append(f"[dry-run] {schema} {key} -> {before}")
            continue
        try:
            if before is None:
                u.gsettings_reset(schema, key, schemadir)
            else:
                u.gsettings_set_raw(schema, key, before, schemadir)
            restored.append(f"{schema} {key}")
        except u.CommandError as exc:
            log.warning("could not restore %s %s: %s", schema, key, exc)
    return restored


def _path_owned(backup_dir: Path | None, path: Path) -> bool:
    """True if the path did not exist before this project touched it."""
    if backup_dir is None:
        return False
    for name in ("managed-paths.json", "files-snapshot.json"):
        snapshot_path = Path(backup_dir) / name
        if not snapshot_path.exists():
            continue
        snapshot = u.read_json(snapshot_path)
        entry = snapshot.get(str(path))
        if entry is not None:
            return not entry.get("exists", False)
    return False


def remove_managed_files(backup_dir: Path | None, *, dry_run: bool = False,
                         include_gtk_overrides: bool = True) -> list[str]:
    removed: list[str] = []
    for pattern in OWNED_PATHS:
        path = Path(pattern).expanduser()
        if not include_gtk_overrides and "gtk-4.0" in pattern:
            continue
        if not (path.exists() or path.is_symlink()):
            continue
        if not _path_owned(backup_dir, path):
            # Pre-existing user file: restore it from the backup instead.
            if backup_dir and (Path(backup_dir) / "files-snapshot.json").exists():
                continue
            log.debug("leaving pre-existing path in place: %s", path)
            continue
        if dry_run:
            removed.append(f"[dry-run] remove {path}")
            continue
        u.remove_path(path)
        removed.append(str(path))
    return removed


def uninstall(root: Path, state: State, *, backup_dir: Path | None = None,
              dry_run: bool = False, restore_backup: bool = True) -> dict:
    result = {"settings_restored": [], "files_removed": [], "actions": []}
    backup_dir = Path(backup_dir) if backup_dir else backup_manager.latest_backup(root)

    if restore_backup and backup_dir:
        result["actions"].append(f"using backup {backup_dir}")

    # Extensions: disable first so a running shell stops using the theme.
    for uuid in ("tpct-mac-shell@tpct",
                 "blur-my-shell@aunetx",
                 "macos-dock@vinnytherobot.github.io",
                 "user-theme@gnome-shell-extensions.gcampax.github.com"):
        if extension_manager.installed(uuid):
            try:
                extension_manager.disable(uuid, dry_run=dry_run)
            except u.CommandError as exc:
                log.warning("could not disable %s: %s", uuid, exc)

    result["settings_restored"] = restore_managed_settings(state, dry_run=dry_run)
    result["files_removed"] = remove_managed_files(backup_dir, dry_run=dry_run)

    if backup_dir and restore_backup and not dry_run:
        try:
            restored = backup_manager.restore_saved_files(backup_dir)
            result["actions"].extend(restored)
        except u.EngineError as exc:
            log.warning("could not restore saved files: %s", exc)

    # Runtime pieces created after the original backup may not be listed in its
    # managed-path snapshot; verify our marker before removing them.
    extra = [u.data_home() / "macos-tahoe-ubuntu/appearance",
             Path.home() / ".local/bin/tahoe-appearance-follow",
             u.config_home() / "autostart/tahoe-appearance.desktop"]
    for path in extra:
        if not (path.exists() or path.is_symlink()):
            continue
        marker = False
        try:
            if path.is_dir():
                marker = (path / "appearance.json").exists()
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                marker = ("macos-tahoe" in text or "tahoe-appearance" in text)
        except OSError:
            marker = False
        if not marker:
            continue
        if dry_run:
            result["files_removed"].append(f"[dry-run] remove {path}")
        else:
            u.remove_path(path)
            result["files_removed"].append(str(path))

    app_manager.remove(dry_run=dry_run)
    for uuid in ("tpct-mac-shell@tpct",
                 "user-theme@gnome-shell-extensions.gcampax.github.com",
                 "blur-my-shell@aunetx",
                 "macos-dock@vinnytherobot.github.io"):
        if extension_manager.installed(uuid):
            extension_manager.remove(uuid, dry_run=dry_run)

    if not dry_run:
        state.installation["uninstalled_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        state.installation["resume_required"] = False
        state.save()
    return result
