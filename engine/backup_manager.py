"""Create and restore machine-specific backups.

Backups are deliberately separate from the reusable project data: they capture
*this* machine's pre-installation state and are never bundled into a release.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import utilities as u
from .system_detect import detect

log = logging.getLogger("engine")

PROJECT_VERSION = "1.1.2"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unique_dir(base: Path, name: str) -> Path:
    candidate = base / name
    counter = 2
    while candidate.exists():
        candidate = base / f"{name}-{counter}"
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _safe_rel(home: Path, path: Path) -> str:
    try:
        return path.relative_to(home).as_posix()
    except ValueError:
        return "external/" + path.as_posix().lstrip("/")


def _wallpaper_path(uri: str | None) -> Path | None:
    if not uri:
        return None
    try:
        return Path(unquote(urlparse(uri.strip("'")).path))
    except (ValueError, TypeError):
        return None


def _dconf_dump() -> str:
    proc = u.run(["dconf", "dump", "/"], check=False, timeout=120)
    if proc.returncode != 0:
        raise u.CommandError(["dconf", "dump", "/"], proc.returncode,
                             proc.stdout, proc.stderr)
    return proc.stdout


def _gsettings_recursive(schemas: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for schema in schemas:
        if not u.gsettings_schema_exists(schema):
            continue
        proc = u.run(["gsettings", "list-recursively", schema], check=False, timeout=30)
        if proc.returncode == 0:
            data[schema] = proc.stdout
    return data


def _dpkg_list() -> str:
    proc = u.run(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\n"],
                 check=False, timeout=180)
    return proc.stdout or ""


def _fc_list() -> str:
    proc = u.run(["fc-list", ": family", "file"], check=False, timeout=120)
    return proc.stdout or ""


def _path_state(paths: list[Path]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for path in paths:
        state[str(path)] = {
            "exists": path.exists(),
            "is_symlink": path.is_symlink(),
            "kind": "dir" if path.is_dir() else "file" if path.exists() else None,
        }
    return state


def create_backup(root: Path, reason: str = "pre-install", *,
                  extra_paths: list[Path] | None = None) -> Path:
    """Snapshot the current GNOME/desktop state. Never overwrites a backup."""
    home = Path.home()
    base = Path(root) / "backups"
    base.mkdir(parents=True, exist_ok=True)
    folder = _unique_dir(base, f"{_now()}_{reason}")
    (folder / "files").mkdir()

    system = detect()
    u.atomic_write_json(folder / "system-info.json", system)
    u.atomic_write_text(folder / "dconf.ini", _dconf_dump())

    schemas = [
        "org.gnome.desktop.interface",
        "org.gnome.desktop.wm.preferences",
        "org.gnome.desktop.background",
        "org.gnome.desktop.screensaver",
        "org.gnome.desktop.peripherals.touchpad",
        "org.gnome.desktop.peripherals.mouse",
        "org.gnome.shell",
        "org.gnome.shell.keybindings",
        "org.gnome.shell.app-switcher",
        "org.gnome.mutter",
        "org.gnome.nautilus.preferences",
        "org.gnome.nautilus.icon-view",
        "org.gnome.nautilus.list-view",
        "org.gnome.settings-daemon.plugins.media-keys",
        "org.gnome.shell.extensions.dash-to-dock",
        "org.gnome.shell.extensions.ding",
        "org.gnome.shell.extensions.user-theme",
    ]
    u.atomic_write_json(folder / "gsettings-recursive.json", _gsettings_recursive(schemas))
    u.atomic_write_json(folder / "extensions.json", system["extensions"])
    u.atomic_write_text(folder / "interface.json",
                        json.dumps(system["interface"], indent=2) + "\n")
    u.atomic_write_text(folder / "packages.txt", _dpkg_list())
    u.atomic_write_text(folder / "fonts.txt", _fc_list())

    # Save the currently selected wallpapers when they live in the user's home.
    wallpapers: dict[str, str] = {}
    for key in ("picture-uri", "picture-uri-dark"):
        path = _wallpaper_path(u.gsettings_get("org.gnome.desktop.background", key))
        if path and path.exists() and str(path).startswith(str(home)):
            rel = f"wallpapers/{key}-{path.name}"
            destination = folder / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            wallpapers[key] = rel
        elif path:
            wallpapers[key] = str(path)
    u.atomic_write_json(folder / "wallpapers.json", wallpapers)

    # Files this project may modify: keep a byte-exact copy.
    file_targets = [
        u.config_home() / "gtk-3.0/gtk.css",
        u.config_home() / "gtk-4.0/gtk.css",
        u.config_home() / "gtk-4.0/gtk-dark.css",
        u.config_home() / "gtk-4.0/assets",
        u.config_home() / "gtk-4.0/windows-assets",
        u.config_home() / "rofi",
        u.config_home() / "tpct-mac",
        home / ".local/bin/tahoe-spotlight",
        u.config_home() / "autostart/ulauncher.desktop",
    ]
    if extra_paths:
        file_targets.extend(extra_paths)
    copied: dict[str, Any] = {}
    for path in file_targets:
        if not path.exists():
            copied[str(path)] = {"existed": False}
            continue
        rel = _safe_rel(home, path)
        target = folder / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target, symlinks=True)
            copied[str(path)] = {"existed": True, "kind": "dir", "stored": rel}
        else:
            shutil.copy2(path, target, follow_symlinks=False)
            copied[str(path)] = {"existed": True, "kind": "file", "stored": rel,
                                 "sha256": u.sha256_file(path)}
    u.atomic_write_json(folder / "files-snapshot.json", copied)

    # Record which managed destinations already existed (never restore these
    # blindly into a different machine).
    managed = [
        u.data_home() / "themes/TPCT-Mac-Dark",
        u.data_home() / "themes/TPCT-Mac-Light",
        u.data_home() / "icons/WhiteSur-dark",
        u.data_home() / "icons/WhiteSur-light",
        u.data_home() / "icons/WhiteSur-cursors",
        u.data_home() / "fonts/Inter-Variable.ttf",
        u.data_home() / "backgrounds/macos-tahoe",
        u.data_home() / "gnome-shell/extensions/tpct-mac-shell@tpct",
        u.data_home() / "gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com",
        u.data_home() / "gnome-shell/extensions/blur-my-shell@aunetx",
        u.data_home() / "gnome-shell/extensions/macos-dock@vinnytherobot.github.io",
        u.data_home() / "macos-tahoe-ubuntu",
    ]
    u.atomic_write_json(folder / "managed-paths.json", _path_state(managed))

    manifest = {
        "schema_version": 1,
        "project": "macos-tahoe-ubuntu",
        "project_version": PROJECT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "machine": system["user"],
        "os": system["os"],
        "files": {},
    }
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            manifest["files"][path.relative_to(folder).as_posix()] = u.sha256_file(path)
    u.atomic_write_json(folder / "MANIFEST.json", manifest)
    log.info("backup created: %s", folder)
    return folder


def verify_backup(folder: Path) -> tuple[bool, list[str]]:
    folder = Path(folder)
    problems: list[str] = []
    try:
        manifest = u.read_json(folder / "MANIFEST.json")
    except u.ConfigError as exc:
        return False, [str(exc)]
    for rel, digest in manifest.get("files", {}).items():
        path = folder / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
        elif u.sha256_file(path) != digest:
            problems.append(f"checksum mismatch: {rel}")
    return not problems, problems


def list_backups(root: Path) -> list[Path]:
    base = Path(root) / "backups"
    if not base.is_dir():
        return []
    return sorted([p for p in base.iterdir() if p.is_dir() and (p / "MANIFEST.json").exists()])


def latest_backup(root: Path) -> Path | None:
    backups = list_backups(root)
    return backups[-1] if backups else None


def resolve_backup(root: Path, selector: str | None = None) -> Path:
    if selector:
        candidate = Path(selector)
        if not candidate.is_absolute():
            candidate = Path(root) / "backups" / selector
        if not (candidate / "MANIFEST.json").exists():
            raise u.EngineError(f"backup not found: {candidate}")
        return candidate
    latest = latest_backup(root)
    if latest is None:
        raise u.EngineError("no backups are available")
    return latest


def restore_dconf(folder: Path, *, dry_run: bool = False) -> None:
    """Restore the full dconf snapshot taken on this machine."""
    folder = Path(folder)
    dump = folder / "dconf.ini"
    if not dump.exists():
        raise u.EngineError(f"backup has no dconf.ini: {folder}")
    if dry_run:
        log.info("[dry-run] would load %s into dconf", dump)
        return
    text = dump.read_text(encoding="utf-8")
    proc = u.run(["dconf", "load", "/"], check=False, timeout=120, input_text=text)
    if proc.returncode != 0:
        raise u.CommandError(["dconf", "load", "/"], proc.returncode,
                             proc.stdout, proc.stderr)


def restore_saved_files(folder: Path, *, dry_run: bool = False) -> list[str]:
    """Restore user files captured in files-snapshot.json.

    Paths that did not exist before are removed if the project created them.
    """
    folder = Path(folder)
    snapshot = u.read_json(folder / "files-snapshot.json", required=False) or {}
    restored: list[str] = []
    for original, info in snapshot.items():
        path = Path(original)
        if info.get("existed"):
            stored = folder / "files" / info["stored"]
            if not stored.exists():
                log.warning("backup file missing, skipping: %s", stored)
                continue
            if dry_run:
                restored.append(f"[dry-run] restore {path}")
                continue
            u.remove_path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if info.get("kind") == "dir":
                shutil.copytree(stored, path, symlinks=True)
            else:
                shutil.copy2(stored, path, follow_symlinks=False)
            restored.append(str(path))
        else:
            # The project created this path; remove it on restore.
            if path.exists() or path.is_symlink():
                if dry_run:
                    restored.append(f"[dry-run] remove {path}")
                else:
                    u.remove_path(path)
                    restored.append(f"removed {path}")
    return restored
