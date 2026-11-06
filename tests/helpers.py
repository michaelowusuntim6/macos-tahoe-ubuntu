"""Shared helpers for the test suite."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import utilities as u  # noqa: E402


def fake_system(*, release: str = "26.04", gnome_major: int = 50,
                session: str = "wayland", distro: str = "ubuntu",
                ram: int = 15359, free_disk: int = 44000,
                enabled_extensions: list[str] | None = None) -> dict:
    return {
        "timestamp": "2026-11-05T00:00:00",
        "os": {"id": distro, "id_like": "debian", "name": "Ubuntu",
               "pretty_name": f"Ubuntu {release} LTS", "version_id": release,
               "codename": "resolute", "kernel": "7.0.0", "arch": "x86_64"},
        "desktop": {"shell": "ubuntu:GNOME", "session": session,
                    "session_desktop": "ubuntu", "gnome_shell": f"{gnome_major}.1",
                    "gnome_major": gnome_major, "display": "wayland-0",
                    "resolution": "1366x768"},
        "hardware": {"vendor": "TOSHIBA", "model": "SATELLITE PRO C850-1ER",
                     "cpu": "Intel Core i5-3210M", "cores": 4, "ram_mb": ram,
                     "gpu": {"names": ["Intel HD Graphics 4000"], "driver": "i915",
                             "renderer": "Mesa Intel HD Graphics 4000"},
                     "disk_home": {"total_mb": 120000, "free_mb": free_disk}},
        "user": {"name": "mike", "home": "/home/mike", "hostname": "test"},
        "tools": {"python3": "/usr/bin/python3", "gsettings": "/usr/bin/gsettings",
                  "dconf": "/usr/bin/dconf", "gnome-extensions": "/usr/bin/gnome-extensions",
                  "gnome-shell": "/usr/bin/gnome-shell", "apt-get": "/usr/bin/apt-get",
                  "dpkg-query": "/usr/bin/dpkg-query", "curl": "/usr/bin/curl",
                  "wget": "/usr/bin/wget", "tar": "/usr/bin/tar", "unzip": "/usr/bin/unzip",
                  "sha256sum": "/usr/bin/sha256sum", "fc-cache": "/usr/bin/fc-cache",
                  "rsync": "/usr/bin/rsync", "rofi": None, "sassc": None},
        "extensions": {
            "installed": {},
            "enabled": enabled_extensions or [
                "ding@rastersoft.com", "ubuntu-dock@ubuntu.com",
                "tiling-assistant@ubuntu.com", "gsconnect@andyholmes.github.io",
                "ubuntu-appindicators@ubuntu.com"],
            "disabled": [],
        },
        "interface": {
            "gtk-theme": "'Yaru-dark'", "icon-theme": "'Yaru-dark'",
            "cursor-theme": "'Yaru'", "font-name": "'Ubuntu Sans 11'",
            "color-scheme": "'prefer-dark'", "button-layout": "':minimize,maximize,close'",
            "wallpaper": "'file:///usr/share/backgrounds/default.jpg'",
            "wallpaper-dark": None, "shell-theme": None,
            "dock": {},
        },
        "packages": {"rofi": False, "sassc": False, "fonts-inter": False,
                     "qt-style-kvantum": False, "gnome-weather": True},
        "network_online": True,
    }


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
