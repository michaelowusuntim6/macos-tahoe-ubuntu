"""Detect the operating system, desktop environment and hardware."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from . import utilities as u

DASH_TO_DOCK = "org.gnome.shell.extensions.dash-to-dock"


def _command_version(argv: list[str]) -> str | None:
    if not shutil.which(argv[0]):
        return None
    proc = u.run(argv, check=False, timeout=20)
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr).strip() else None


def _gpu_info() -> dict[str, Any]:
    names: list[str] = []
    drivers: list[str] = []
    if shutil.which("lspci"):
        proc = u.run(["lspci", "-nnk"], check=False, timeout=20)
        current: list[str] = []
        blocks: list[list[str]] = []
        for line in (proc.stdout or "").splitlines():
            if line and not line.startswith(("\t", " ")):
                if current:
                    blocks.append(current)
                current = [line]
            elif current:
                current.append(line)
        if current:
            blocks.append(current)
        for block in blocks:
            head = block[0]
            if not re.search(r"(VGA compatible|3D controller|Display controller)", head):
                continue
            names.append(re.sub(r"\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]\s*", " ", head).strip())
            for line in block[1:]:
                m = re.search(r"Kernel driver in use:\s*(\S+)", line)
                if m:
                    drivers.append(m.group(1))
    return {"names": names, "driver": drivers[0] if drivers else None,
            "drivers": drivers, "renderer": _gl_renderer()}


def _gl_renderer() -> str | None:
    """Best-effort GPU renderer string (works without an X display too)."""
    for cmd in (["glxinfo", "-B"], ["eglinfo"]):
        if not shutil.which(cmd[0]):
            continue
        proc = u.run(cmd, check=False, timeout=20)
        for line in (proc.stdout or "").splitlines():
            if "Renderer" in line or "Device:" in line:
                return line.strip()
    return None


def _ram_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(int(line.split()[1]) / 1024)
    except (OSError, ValueError):
        pass
    return None


def _disk(path: Path) -> dict[str, int | None]:
    try:
        st = os.statvfs(path)
        return {
            "total_mb": int(st.f_blocks * st.f_frsize / 1024 / 1024),
            "free_mb": int(st.f_bavail * st.f_frsize / 1024 / 1024),
        }
    except OSError:
        return {"total_mb": None, "free_mb": None}


def _screen_resolution() -> str | None:
    if shutil.which("xrandr"):
        proc = u.run(["xrandr"], check=False, timeout=15)
        for line in (proc.stdout or "").splitlines():
            if "*" in line and re.match(r"\s+\d+x\d+", line):
                return line.split()[0]
    return None


def _extensions() -> dict[str, Any]:
    installed: dict[str, dict] = {}
    roots = [
        u.data_home() / "gnome-shell/extensions",
        Path("/usr/share/gnome-shell/extensions"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for ext in sorted(root.iterdir()):
            meta = ext / "metadata.json"
            if not meta.exists():
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            uuid = data.get("uuid", ext.name)
            installed.setdefault(uuid, {
                "uuid": uuid,
                "name": data.get("name"),
                "shell_versions": data.get("shell-version", []),
                "version": data.get("version"),
                "path": str(ext),
                "source": "user" if str(ext).startswith(str(Path.home())) else "system",
            })
    enabled = u.gsettings_array(u.gsettings_get("org.gnome.shell", "enabled-extensions"))
    disabled = u.gsettings_array(u.gsettings_get("org.gnome.shell", "disabled-extensions"))
    return {"installed": installed, "enabled": enabled, "disabled": disabled}


def _interface_state() -> dict[str, Any]:
    keys = ["gtk-theme", "icon-theme", "cursor-theme", "font-name",
            "document-font-name", "monospace-font-name", "color-scheme",
            "accent-color", "text-scaling-factor"]
    state: dict[str, Any] = {}
    for key in keys:
        state[key] = u.gsettings_get("org.gnome.desktop.interface", key)
    state["button-layout"] = u.gsettings_get("org.gnome.desktop.wm.preferences", "button-layout")
    state["titlebar-font"] = u.gsettings_get("org.gnome.desktop.wm.preferences", "titlebar-font")
    state["wallpaper"] = u.gsettings_get("org.gnome.desktop.background", "picture-uri")
    state["wallpaper-dark"] = u.gsettings_get("org.gnome.desktop.background", "picture-uri-dark")
    state["shell-theme"] = u.gsettings_get(
        "org.gnome.shell.extensions.user-theme", "name",
        u.settings_schemadir("org.gnome.shell.extensions.user-theme"))
    dock: dict[str, Any] = {}
    for key in ("dock-position", "dash-max-icon-size", "dock-fixed", "autohide",
                "intellihide", "extend-height", "background-opacity", "transparency-mode"):
        dock[key] = u.gsettings_get(DASH_TO_DOCK, key)
    state["dock"] = dock
    return state


def detected_packages(names: list[str]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    if not shutil.which("dpkg-query"):
        return {n: False for n in names}
    for name in names:
        proc = u.run(["dpkg-query", "-W", "-f=${Status}", name], check=False, timeout=15)
        result[name] = "install ok installed" in (proc.stdout or "")
    return result


def detect() -> dict[str, Any]:
    osr = u.parse_os_release()
    version = osr.get("VERSION_ID", "")
    shell = u.gnome_shell_version()
    major = int(shell.split(".")[0]) if shell and shell[0].isdigit() else None
    home_disk = _disk(Path.home())
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "os": {
            "id": osr.get("ID"),
            "id_like": osr.get("ID_LIKE"),
            "name": osr.get("NAME"),
            "pretty_name": osr.get("PRETTY_NAME"),
            "version_id": version,
            "codename": osr.get("VERSION_CODENAME") or osr.get("UBUNTU_CODENAME"),
            "kernel": platform.release(),
            "arch": platform.machine(),
        },
        "desktop": {
            "shell": os.environ.get("XDG_CURRENT_DESKTOP"),
            "session": u.session_type(),
            "session_desktop": os.environ.get("DESKTOP_SESSION"),
            "gnome_shell": shell,
            "gnome_major": major,
            "display": os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
            "resolution": _screen_resolution(),
        },
        "hardware": {
            "vendor": _read_first("/sys/class/dmi/id/sys_vendor"),
            "model": _read_first("/sys/class/dmi/id/product_name"),
            "cpu": _cpu_model(),
            "cores": os.cpu_count(),
            "ram_mb": _ram_mb(),
            "gpu": _gpu_info(),
            "disk_home": home_disk,
        },
        "user": {"name": os.environ.get("USER") or _read_first("/proc/self/loginuid"),
                 "home": str(Path.home()), "hostname": socket.gethostname()},
        "tools": {name: shutil.which(name) for name in (
            "python3", "gsettings", "dconf", "gnome-extensions", "gnome-shell",
            "apt-get", "dpkg-query", "curl", "wget", "tar", "unzip", "sha256sum",
            "fc-cache", "rsync", "rofi", "sassc")},
        "extensions": _extensions(),
        "interface": _interface_state(),
        "packages": detected_packages(["rofi", "sassc", "fonts-inter",
                                       "qt-style-kvantum", "gnome-weather"]),
        "network_online": _online(),
    }


def _read_first(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _online() -> bool:
    import socket as _socket
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            s = _socket.create_connection((host, 443), timeout=3)
            s.close()
            return True
        except OSError:
            continue
    return False
