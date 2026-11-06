#!/usr/bin/env python3
"""Capture production-like screenshots in the isolated headless shell.

Mirrors the live dconf configuration into a private session, then captures:
  reports/visual-dark.png        desktop, dock visible, pointer over an icon
  reports/visual-light.png       same in light mode
  reports/visual-control-center.png
  reports/visual-app-window.png  a GTK4 application with traffic lights

Requires an installed session (run ./install.sh first).  No logout is needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import headless_test, utilities as u  # noqa: E402

REPORTS = ROOT / "reports"
DEBUG = "tahoe-debug@tahoe"
MANAGED = [
    "user-theme@gnome-shell-extensions.gcampax.github.com",
    "tpct-mac-shell@tpct",
    "blur-my-shell@aunetx",
    "macos-dock@vinnytherobot.github.io",
]


def live_enabled() -> list[str]:
    raw = u.gsettings_get("org.gnome.shell", "enabled-extensions")
    enabled = u.gsettings_array(raw)
    # DING's desktop window paints over the wallpaper in the nested shell.
    enabled = [e for e in enabled if e not in ("ding@rastersoft.com",
                                               "ubuntu-dock@ubuntu.com")]
    if DEBUG not in enabled:
        enabled.append(DEBUG)
    return enabled


def dock_hover_js(x: int, y: int) -> str:
    return ("(() => { global.get_pointer = function() { return [%d, %d]; }; "
            "return 'pointer patched'; })()" % (x, y))


def capture(mode: str) -> dict:
    dark = mode == "dark"
    settings = [
        ("org.gnome.shell.extensions.macosdock", "auto-hide", False),
    ]
    if not dark:
        settings += [
            ("org.gnome.desktop.interface", "color-scheme", "prefer-light"),
            ("org.gnome.desktop.interface", "gtk-theme", "TPCT-Mac-Light"),
            ("org.gnome.desktop.interface", "icon-theme", "WhiteSur-light"),
            ("org.gnome.shell.extensions.macosdock", "dock-background-color", "#3275c0"),
            ("org.gnome.shell.extensions.macosdock", "dock-opacity", 30),
            ("org.gnome.shell.extensions.macosdock", "custom-css",
             " ".join((ROOT / "assets/dock/liquid-dock-light.css")
                      .read_text().split())),
            ("org.gnome.shell.extensions.blur-my-shell.panel", "brightness", 0.86),
            ("org.gnome.shell.extensions.blur-my-shell.popup", "brightness", 0.86),
            ("org.gnome.shell.extensions.blur-my-shell.panel", "sigma", 24),
            ("org.gnome.shell.extensions.blur-my-shell.popup", "sigma", 28),
        ]
    theme_name = "TPCT-Mac-Light" if not dark else "TPCT-Mac-Dark"
    # user-theme name is set below through its schema directory by the harness.
    settings.append(("org.gnome.shell.extensions.user-theme", "name", theme_name))
    return headless_test.run(
        ROOT,
        screenshot=REPORTS / f"visual-{mode}.png",
        dark=dark,
        enabled_extensions=live_enabled(),
        extra_settings=settings,
        mirror_dconf=True,
        eval_js=dock_hover_js(690, 706),
        eval_wait=1.6,
        state_uuids=MANAGED,
    )


def capture_control_center(mode: str = "dark") -> dict:
    dark = mode == "dark"
    expr = ("(() => { try { Main.panel.statusArea.quickSettings.menu.open(); "
            "return 'opened'; } catch (e) { return 'ERR ' + e; } })()")
    settings = []
    if not dark:
        settings = [
            ("org.gnome.desktop.interface", "color-scheme", "prefer-light"),
            ("org.gnome.desktop.interface", "gtk-theme", "TPCT-Mac-Light"),
            ("org.gnome.desktop.interface", "icon-theme", "WhiteSur-light"),
            ("org.gnome.shell.extensions.user-theme", "name", "TPCT-Mac-Light"),
            ("org.gnome.shell.extensions.macosdock", "dock-background-color", "#3275c0"),
            ("org.gnome.shell.extensions.macosdock", "custom-css",
             " ".join((ROOT / "assets/dock/liquid-dock-light.css").read_text().split())),
            ("org.gnome.shell.extensions.blur-my-shell.panel", "brightness", 0.86),
            ("org.gnome.shell.extensions.blur-my-shell.popup", "brightness", 0.86),
        ]
    return headless_test.run(
        ROOT,
        screenshot=REPORTS / f"visual-control-center-{mode}.png",
        dark=dark,
        enabled_extensions=live_enabled(),
        extra_settings=settings,
        mirror_dconf=True,
        eval_js=expr,
        eval_wait=2.2,
        state_uuids=MANAGED,
    )


def capture_app() -> dict:
    return headless_test.run(
        ROOT,
        screenshot=REPORTS / "visual-app-window.png",
        dark=True,
        enabled_extensions=live_enabled(),
        extra_settings=[],
        mirror_dconf=True,
        launch=["gnome-text-editor", "--new-window"],
        launch_wait=6,
        state_uuids=MANAGED,
    )


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    results = {}
    for mode in ("dark", "light"):
        print(f"capturing {mode} desktop…")
        results[mode] = capture(mode)
    print("capturing Control Centers…")
    results["control-center-dark"] = capture_control_center("dark")
    results["control-center-light"] = capture_control_center("light")
    print("capturing application window…")
    results["app"] = capture_app()
    summary = {name: {"ok": r.get("ok"), "screenshot": r.get("screenshot"),
                      "states": r.get("states"), "errors": r.get("errors")}
               for name, r in results.items()}
    (REPORTS / "visual-capture.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if all(v.get("ok") for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
