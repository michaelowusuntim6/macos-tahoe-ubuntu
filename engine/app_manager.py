"""macOS-style display names for a small set of stock applications.

The original .desktop files are never modified.  Local overrides in
~/.local/share/applications are created with an ownership marker so they can be
removed cleanly.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from . import utilities as u

log = logging.getLogger("engine")

MARKER = "X-Tahoe-Mac=true"

NAMES = {
    "org.gnome.Nautilus.desktop": "Finder",
    "org.gnome.Settings.desktop": "System Settings",
    "org.gnome.Software.desktop": "App Store",
    "snap-store_snap-store.desktop": "App Store",
    "org.gnome.TextEditor.desktop": "TextEdit",
    "org.gnome.Loupe.desktop": "Preview",
    "org.gnome.Papers.desktop": "Preview",
    "org.gnome.Ptyxis.desktop": "Terminal",
    "org.gnome.SystemMonitor.desktop": "Activity Monitor",
    "org.gnome.DiskUtility.desktop": "Disk Utility",
    "org.gnome.baobab.desktop": "Storage",
    "org.gnome.clocks.desktop": "Clock",
    "org.gnome.font-viewer.desktop": "Font Book",
    "org.gnome.Characters.desktop": "Character Viewer",
    "org.gnome.Showtime.desktop": "QuickTime Player",
    "org.gnome.Totem.desktop": "QuickTime Player",
}

SOURCE_DIRS = [
    Path("/usr/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    u.data_home() / "flatpak/exports/share/applications",
]


def _rewrite(text: str, name: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("Name[") or line.startswith("X-GNOME-FullName"):
            continue
        if not replaced and line.startswith("Name="):
            out.append(f"Name={name}")
            replaced = True
            continue
        if line == MARKER:
            continue
        out.append(line)
    if not replaced:
        return text
    if MARKER not in out:
        out.append(MARKER)
    return "\n".join(out) + "\n"


def install(root: Path, *, dry_run: bool = False) -> list[str]:
    dest = u.data_home() / "applications"
    created: list[str] = []
    for filename, name in NAMES.items():
        source = next((d / filename for d in SOURCE_DIRS if (d / filename).is_file()), None)
        if source is None:
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("cannot read %s: %s", source, exc)
            continue
        new_text = _rewrite(text, name)
        target = dest / filename
        if target.exists() and target.read_text(encoding="utf-8", errors="replace") == new_text:
            created.append(str(target))
            continue
        if dry_run:
            log.info("[dry-run] would name %s as %r", filename, name)
            created.append(str(target))
            continue
        u.atomic_write_text(target, new_text)
        created.append(str(target))
    if not dry_run and created:
        u.run(["update-desktop-database", str(dest)], check=False, timeout=60)
        log.info("applied macOS display names to %d applications", len(created))
    return created


def remove(*, dry_run: bool = False) -> None:
    dest = u.data_home() / "applications"
    if not dest.is_dir():
        return
    for path in dest.glob("*.desktop"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if MARKER not in text:
            continue
        if dry_run:
            log.info("[dry-run] would remove app override %s", path)
            continue
        path.unlink(missing_ok=True)
    if not dry_run:
        u.run(["update-desktop-database", str(dest)], check=False, timeout=60)


TRASH_ENTRY = """[Desktop Entry]
Type=Application
Name=Trash
GenericName=Trash
Comment=Open the Trash
Exec=nautilus trash://
Icon=user-trash
Terminal=false
Categories=System;FileManager;
StartupNotify=true
X-Tahoe-Mac=true
"""


def install_trash(*, dry_run: bool = False) -> Path:
    """Create a Trash launcher that MacOSDock can pin (it has no built-in trash)."""
    dest = u.data_home() / "applications/tahoe-trash.desktop"
    if dest.exists() and dest.read_text(encoding="utf-8") == TRASH_ENTRY:
        return dest
    if dry_run:
        log.info("[dry-run] would create Trash launcher %s", dest)
        return dest
    u.atomic_write_text(dest, TRASH_ENTRY)
    u.run(["update-desktop-database", str(dest.parent)], check=False, timeout=60)
    return dest
