#!/usr/bin/env python3
"""Keep GTK, icons, the Shell theme, dock glass and blur in sync with the
system Light/Dark switch.

Installed to ~/.local/bin/tahoe-appearance-follow and started from
~/.config/autostart.  No third-party modules are used.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

BEGIN = "/* macos-tahoe-ubuntu: begin */"
END = "/* macos-tahoe-ubuntu: end */"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def log(message: str) -> None:
    try:
        directory = Path.home() / ".cache"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with (directory / "macos-tahoe-appearance.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass


def run(argv: list[str], timeout: float = 20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"command failed {' '.join(argv)}: {exc}")
        return None


def gset(schema: str, key: str, value: str, schemadir: Path | None = None) -> None:
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["set", schema, key, value]
    run(argv)


def enforce_single_dock() -> None:
    """Ubuntu's session mode force-enables its dock; blacklist it and keep ours."""
    enabled_raw = run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"])
    disabled_raw = run(["gsettings", "get", "org.gnome.shell", "disabled-extensions"])
    import ast
    def parse(raw):
        try:
            value = ast.literal_eval(raw or "[]")
            return [str(v) for v in value]
        except (ValueError, SyntaxError):
            return []
    enabled = parse(enabled_raw.stdout if enabled_raw else "[]")
    disabled = parse(disabled_raw.stdout if disabled_raw else "[]")
    desired_dock = "macos-dock@vinnytherobot.github.io"
    conflict = "ubuntu-dock@ubuntu.com"
    changed = False
    if conflict in enabled:
        enabled.remove(conflict)
        changed = True
    if conflict not in disabled:
        disabled.append(conflict)
        changed = True
    if desired_dock not in enabled:
        enabled.append(desired_dock)
        changed = True
    if desired_dock in disabled:
        disabled.remove(desired_dock)
        changed = True
    if changed:
        gset("org.gnome.shell", "enabled-extensions",
             "[" + ", ".join(f"'{e}'" for e in enabled) + "]")
        gset("org.gnome.shell", "disabled-extensions",
             "[" + ", ".join(f"'{e}'" for e in disabled) + "]")
        log("enforced single dock (macOS dock on, Ubuntu Dock blacklisted)")


def read_mode() -> str:
    proc = run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
    if proc and "light" in (proc.stdout or ""):
        return "light"
    return "dark"


def update_gtk3(css_file: Path) -> None:
    target = config_home() / "gtk-3.0/gtk.css"
    block = css_file.read_text(encoding="utf-8").strip()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    cleaned = re.sub(r"/\* macos-tahoe-ubuntu: begin \*/.*?/\* macos-tahoe-ubuntu: end \*/\n?",
                     "", existing, flags=re.S)
    text = cleaned.rstrip() + "\n\n" + f"{BEGIN}\n{block}\n{END}\n"
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def main() -> int:
    appearance_dir = data_home() / "macos-tahoe-ubuntu/appearance"
    config_file = appearance_dir / "appearance.json"
    if not config_file.exists():
        log(f"missing {config_file}; nothing to do")
        return 1
    spec = json.loads(config_file.read_text(encoding="utf-8"))
    ext_root = data_home() / "gnome-shell/extensions"
    user_theme_schema = (ext_root
                         / "user-theme@gnome-shell-extensions.gcampax.github.com/schemas")
    dock_schema = (ext_root / "macos-dock@vinnytherobot.github.io/schemas")
    blur_schema = (ext_root / "blur-my-shell@aunetx/schemas")

    applying = {"busy": False}

    def apply(mode: str) -> None:
        entry = spec["modes"].get(mode)
        if not entry:
            return
        wallpapers = spec.get("wallpapers", {})
        wallpaper_dir = data_home() / "backgrounds/macos-tahoe"
        light_wall = wallpaper_dir / wallpapers.get("light", "tahoe-light.jpg")
        dark_wall = wallpaper_dir / wallpapers.get("dark", "tahoe-dark.jpg")
        if light_wall.exists() and dark_wall.exists():
            gset("org.gnome.desktop.background", "picture-uri",
                 f"'file://{light_wall}'")
            gset("org.gnome.desktop.background", "picture-uri-dark",
                 f"'file://{dark_wall}'")
            gset("org.gnome.desktop.background", "picture-options", "'zoom'")
        gset("org.gnome.desktop.interface", "gtk-theme", f"'{entry['gtk_theme']}'")
        gset("org.gnome.desktop.interface", "icon-theme", f"'{entry['icon_theme']}'")
        if user_theme_schema.exists():
            gset("org.gnome.shell.extensions.user-theme", "name",
                 f"'{entry['shell_theme']}'", user_theme_schema)
        gtk3 = appearance_dir / entry["gtk3_css"]
        if gtk3.exists():
            update_gtk3(gtk3)
        if dock_schema.exists():
            dock_css = appearance_dir / entry["dock_css"]
            if dock_css.exists():
                css = dock_css.read_text(encoding="utf-8")
                gset("org.gnome.shell.extensions.macosdock", "custom-css",
                     json.dumps(css), dock_schema)
            if entry.get("dock_color"):
                gset("org.gnome.shell.extensions.macosdock", "dock-background-color",
                     f"'{entry['dock_color']}'", dock_schema)
            if entry.get("dock_opacity") is not None:
                gset("org.gnome.shell.extensions.macosdock", "dock-opacity",
                     str(entry["dock_opacity"]), dock_schema)
        if blur_schema.exists():
            panel = entry.get("blur", {})
            for schema_name, values in (
                ("org.gnome.shell.extensions.blur-my-shell.panel",
                 {"brightness": panel.get("brightness", 0.72),
                  "sigma": panel.get("sigma_panel", 24)}),
                ("org.gnome.shell.extensions.blur-my-shell.popup",
                 {"brightness": panel.get("brightness", 0.72),
                  "sigma": panel.get("sigma_popup", 30)}),
            ):
                for key, value in values.items():
                    gset(schema_name, key, repr(float(value)), blur_schema)
        log(f"applied {mode} appearance")

    enforce_single_dock()
    apply(read_mode())
    proc = subprocess.Popen(
        ["gsettings", "monitor", "org.gnome.desktop.interface", "color-scheme"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    stopping = {"value": False}

    def stop(_signum, _frame):
        stopping["value"] = True
        try:
            proc.terminate()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if stopping["value"]:
                break
            if "color-scheme" in line:
                apply(read_mode())
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
