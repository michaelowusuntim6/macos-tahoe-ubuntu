"""Apply the desired desktop settings through GSettings, with a change journal."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from . import utilities as u
from .state_manager import State

log = logging.getLogger("engine")

DASH = "org.gnome.shell.extensions.dash-to-dock"
MACOS_DOCK = "org.gnome.shell.extensions.macosdock"
BMS_PANEL = "org.gnome.shell.extensions.blur-my-shell.panel"
BMS_POPUP = "org.gnome.shell.extensions.blur-my-shell.popup"
USER_THEME = "org.gnome.shell.extensions.user-theme"
DING = "org.gnome.shell.extensions.ding"
MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SPOTLIGHT_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/tahoe-spotlight/"


class ConfigApplier:
    def __init__(self, root: Path, state: State, *, dry_run: bool = False,
                 profile: str = "full"):
        self.root = Path(root)
        self.state = state
        self.dry_run = dry_run
        self.profile = profile
        self.desktop = u.read_json(root / "config/desktop.json")
        self.appearance_profiles = u.read_json(root / "config/appearance-profiles.json")
        self.applied: list[str] = []
        self.skipped: list[str] = []
        self.failed: list[str] = []

    # ── low level ─────────────────────────────────────────────────────────
    def _set(self, schema: str, key: str, value: Any, *,
             schemadir: Path | None = None, required: bool = True) -> bool:
        if not u.gsettings_schema_exists(schema, schemadir):
            message = f"schema not available: {schema}"
            (log.error if required else log.debug)(message)
            if required:
                self.failed.append(message)
            return False
        before = u.gsettings_get(schema, key, schemadir)
        after = u.to_gvariant(value)
        if before == after:
            self.skipped.append(f"{schema} {key}")
            return True
        if self.dry_run:
            log.info("[dry-run] %s %s: %s -> %s", schema, key, before, after)
            return True
        try:
            u.gsettings_set(schema, key, value, schemadir)
        except u.CommandError as exc:
            log.error("cannot set %s %s: %s", schema, key, exc)
            self.failed.append(f"{schema} {key}")
            return False
        self.state.record_setting(schema, key, before, after, schemadir)
        self.applied.append(f"{schema} {key}")
        log.debug("%s %s = %s", schema, key, after)
        return True

    def _schemadir(self, schema: str) -> Path | None:
        return u.settings_schemadir(schema)

    # ── appearance ────────────────────────────────────────────────────────
    def apply_appearance(self, mode: str) -> None:
        modes = self.appearance_profiles["modes"]
        if mode not in modes:
            raise u.ConfigError(f"unknown appearance mode: {mode}")
        spec = modes[mode]
        wallpaper_dir = u.data_home() / "backgrounds/macos-tahoe"
        light_wall = wallpaper_dir / modes["light"]["wallpaper"]
        dark_wall = wallpaper_dir / modes["dark"]["wallpaper"]
        for image in (light_wall, dark_wall):
            if not image.exists() and not self.dry_run:
                raise u.EngineError(f"wallpaper missing: {image}")

        self._set("org.gnome.desktop.interface", "gtk-theme", spec["gtk_theme"])
        self._set("org.gnome.desktop.interface", "icon-theme", spec["icon_theme"])
        self._set("org.gnome.desktop.interface", "cursor-theme",
                  self.desktop["appearance"]["cursor_theme"])
        self._set("org.gnome.desktop.interface", "cursor-size",
                  self.desktop["appearance"]["cursor_size"])
        self._set("org.gnome.desktop.interface", "accent-color",
                  self.desktop["appearance"]["accent_color"])
        self._set("org.gnome.desktop.interface", "text-scaling-factor",
                  self.desktop["appearance"]["text_scaling"])
        self._set("org.gnome.desktop.interface", "color-scheme", spec["color_scheme"])
        self._set("org.gnome.desktop.background", "picture-uri",
                  "file://" + str(light_wall))
        self._set("org.gnome.desktop.background", "picture-uri-dark",
                  "file://" + str(dark_wall))

        self._set(USER_THEME, "name", spec["shell_theme"],
                  schemadir=self._schemadir(USER_THEME), required=False)
        self.state.set_component("appearance", "applied", mode=mode,
                                 gtk=spec["gtk_theme"], icons=spec["icon_theme"])

    # ── fonts ─────────────────────────────────────────────────────────────
    def _font_available(self, family: str) -> bool:
        if family == "Inter":
            installed = u.data_home() / "fonts/Inter-Variable.ttf"
            if installed.exists():
                return True
        if not shutil.which("fc-list"):
            return True
        proc = u.run(["fc-list", ": family"], check=False, timeout=30)
        return family.lower() in (proc.stdout or "").lower()

    def apply_fonts(self) -> None:
        fonts = dict(self.desktop["fonts"])
        if not self._font_available("Inter"):
            log.warning("Inter font not available; falling back to Ubuntu Sans")
            fonts = {key: value.replace("Inter", "Ubuntu Sans") for key, value in fonts.items()}
        self._set("org.gnome.desktop.interface", "font-name", fonts["interface"])
        self._set("org.gnome.desktop.interface", "document-font-name", fonts["document"])
        self._set("org.gnome.desktop.interface", "monospace-font-name", fonts["monospace"])
        self._set("org.gnome.desktop.wm.preferences", "titlebar-font", fonts["titlebar"])
        self.state.set_component("fonts", "applied", interface=fonts["interface"])

    # ── generic sections ──────────────────────────────────────────────────
    def apply_sections(self) -> None:
        for schema, settings in self.desktop["gnome"].items():
            for key, value in settings.items():
                self._set(schema, key, value, required=False)

    def apply_dock(self, *, icon_size: int | None = None,
                   mode: str = "dark") -> None:
        """Configure MacOSDock (magnification, glass, spring motion).

        Ubuntu Dock is kept installed but disabled; its schema is still set to
        the same bottom/floating geometry as a fallback if MacOSDock is ever
        unavailable.
        """
        settings = dict(self.desktop["dock"]["settings"])
        if icon_size:
            settings["dash-max-icon-size"] = icon_size
        for key, value in settings.items():
            self._set(DASH, key, value, required=False)

        dock = self.desktop.get("macos_dock")
        if not dock:
            return
        schemadir = self._schemadir(MACOS_DOCK)
        if not schemadir:
            log.warning("MacOSDock schema unavailable; dock configuration skipped")
            return
        values = dict(dock.get("settings", {}))
        values.update(dock.get("profiles", {}).get(self.profile, {}))
        motion_file = self.root / "config/motion.json"
        if motion_file.exists():
            motion = u.read_json(motion_file)
            md = motion.get("dock", {})
            values.update({
                "magnification-scale": md.get("max_scale", 1.45),
                "magnification-falloff": md.get("falloff_px", 125),
                "magnification-framerate": md.get("framerate", 60),
                "magnification-spring-stiffness": md.get("spring", {}).get("stiffness", 320.0),
                "magnification-spring-damping": md.get("spring", {}).get("damping", 26.0),
                "magnification-spring-mass": md.get("spring", {}).get("mass", 1.0),
                "animation-duration": md.get("show_hide_duration_ms", 220),
                "bounce-on-launch": md.get("bounce_on_launch", True),
            })
        palette = u.read_json(self.root / f"config/palette-{mode}.json")
        values["dock-background-color"] = palette["colors"]["background_top"]
        values["dock-opacity"] = 26 if mode == "dark" else 30
        dock_css = self.root / f"assets/dock/liquid-dock-{mode}.css"
        if dock_css.exists():
            values["custom-css"] = " ".join(dock_css.read_text(encoding="utf-8").split())
        for key, value in values.items():
            self._set(MACOS_DOCK, key, value, schemadir=schemadir, required=False)
        self.state.set_component("dock", "applied", implementation="macos-dock",
                                 position="BOTTOM", mode=mode)

    def apply_nautilus(self) -> None:
        self._set("org.gnome.nautilus.preferences", "default-folder-viewer", "icon-view",
                  required=False)
        self.state.set_component("nautilus", "applied")

    def apply_desktop_icons(self) -> None:
        if not u.gsettings_schema_exists(DING):
            return
        for key, value in (("start-corner", "top-right"), ("show-home", False),
                           ("show-trash", False), ("show-volumes", True),
                           ("add-volumes-opposite", False)):
            self._set(DING, key, value, required=False)

    def apply_keybindings(self) -> None:
        for schema, bindings in self.desktop["keybindings"].items():
            for key, value in bindings.items():
                self._set(schema, key, value, required=False)
        self.state.set_component("keybindings", "applied")

    def apply_spotlight(self) -> None:
        spotlight = self.desktop["spotlight"]
        wrapper = Path.home() / ".local/bin" / spotlight["command"]
        if not wrapper.exists() and not self.dry_run:
            log.warning("Spotlight wrapper missing; leaving keyboard shortcut untouched")
            return
        if self.dry_run and not wrapper.exists():
            log.info("[dry-run] %s would be created", wrapper)
        current_raw = u.gsettings_get(MEDIA_KEYS, "custom-keybindings")
        current = u.gsettings_array(current_raw)
        if SPOTLIGHT_PATH not in current:
            current.append(SPOTLIGHT_PATH)
            if not self.dry_run:
                before = current_raw
                u.gsettings_set(MEDIA_KEYS, "custom-keybindings", current)
                self.state.record_setting(MEDIA_KEYS, "custom-keybindings",
                                          before, u.to_gvariant(current))
        schema = f"{MEDIA_KEYS}.custom-keybinding:{SPOTLIGHT_PATH}"
        values = {"name": spotlight["name"], "command": spotlight["command"],
                  "binding": spotlight["binding"]}
        for key, value in values.items():
            if self.dry_run:
                log.info("[dry-run] %s %s = %s", schema, key, value)
                continue
            before = u.gsettings_get(schema, key)
            try:
                u.gsettings_set(schema, key, value)
            except u.CommandError as exc:
                log.error("cannot configure Spotlight shortcut: %s", exc)
                self.failed.append(f"{schema} {key}")
                continue
            self.state.record_setting(schema, key, before, u.to_gvariant(value))
            self.applied.append(f"{schema} {key}")
        self.state.set_component("spotlight", "applied", command=str(wrapper))

    def apply_blur(self, *, mode: str) -> None:
        """Configure real backdrop blur for panel and popovers."""
        bms = u.settings_schemadir(BMS_PANEL)
        if not bms:
            log.warning("Blur my Shell is not installed; glass stays in CSS-only mode")
            return
        palette = u.read_json(self.root / f"config/palette-{mode}.json")
        panel = dict(self.desktop.get("blur", {}).get("panel", {}))
        popup = dict(self.desktop.get("blur", {}).get("popup", {}))
        panel.update({
            "sigma": palette["materials"]["panel"]["blur_sigma"],
            "brightness": 0.72 if mode == "dark" else 0.86,
        })
        popup.update({
            "sigma": palette["materials"]["popover"]["blur_sigma"],
            "brightness": 0.72 if mode == "dark" else 0.86,
        })
        for key, value in panel.items():
            self._set(BMS_PANEL, key, value, schemadir=bms, required=False)
        for key, value in popup.items():
            self._set(BMS_POPUP, key, value, schemadir=bms, required=False)
        # The dash component must not attach to the MacOSDock actors.
        self._set("org.gnome.shell.extensions.blur-my-shell.dash-to-dock",
                  "blur", False, schemadir=bms, required=False)
        self.state.set_component("blur", "applied",
                                 panel_sigma=panel["sigma"], mode=mode)

    def apply_favorites(self) -> None:
        """Append the Trash launcher without disturbing existing favourites."""
        trash = u.data_home() / "applications/tahoe-trash.desktop"
        if not trash.exists() and not self.dry_run:
            return
        raw = u.gsettings_get("org.gnome.shell", "favorite-apps")
        favorites = u.gsettings_array(raw)
        if "tahoe-trash.desktop" in favorites:
            return
        favorites.append("tahoe-trash.desktop")
        if not self.dry_run:
            before = raw
            u.gsettings_set("org.gnome.shell", "favorite-apps", favorites)
            self.state.record_setting("org.gnome.shell", "favorite-apps",
                                      before, u.to_gvariant(favorites))
        self.applied.append("org.gnome.shell favorite-apps")

    def start_appearance_daemon(self) -> None:
        if self.dry_run:
            return
        binary = Path.home() / ".local/bin/tahoe-appearance-follow"
        if not binary.exists():
            return
        proc = u.run(["pgrep", "-f", "tahoe-appearance-follow"], check=False, timeout=10)
        if proc.returncode == 0:
            return
        import subprocess
        try:
            subprocess.Popen([str(binary)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("appearance daemon started")
        except OSError as exc:
            log.warning("could not start appearance daemon: %s", exc)

    def apply_widgets(self) -> None:
        """Install a curated desktop-widget layout on first run only.

        Users can drag widgets freely afterwards; repair never overwrites an
        existing layout.
        """
        layout = self.desktop.get("widgets", {}).get("layout")
        if not layout:
            return
        path = u.config_home() / "tpct-mac/widgets.json"
        if self.dry_run:
            log.info("[dry-run] would install desktop widget layout %s", path)
            return
        if path.exists():
            log.debug("widget layout already exists; leaving it untouched")
            return
        u.atomic_write_json(path, layout)
        self.applied.append(str(path))

    def apply_ptyxis(self) -> None:
        if not u.gsettings_schema_exists("org.gnome.Ptyxis"):
            return
        wrapper_dir = u.data_home() / "org.gnome.Ptyxis/palettes"
        if not (wrapper_dir / "macOS.palette").exists() and not self.dry_run:
            return
        proc = u.run(["gsettings", "get", "org.gnome.Ptyxis", "default-profile-uuid"],
                     check=False, timeout=20)
        uuid = (proc.stdout or "").strip().strip("'")
        if not uuid:
            return
        profile_schema = f"org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/{uuid}/"
        if not self.dry_run:
            before = u.gsettings_get(profile_schema, "palette")
            try:
                u.gsettings_set(profile_schema, "palette", "macOS")
                self.state.record_setting(profile_schema, "palette", before, "'macOS'")
                self.applied.append(f"{profile_schema} palette")
            except u.CommandError as exc:
                log.debug("Ptyxis palette not applied: %s", exc)
        self._set("org.gnome.Ptyxis", "use-system-font", False, required=False)
        self._set("org.gnome.Ptyxis", "font-name", self.desktop["terminal"]["font"],
                  required=False)
        self.state.set_component("terminal", "applied")

    # ── full application ──────────────────────────────────────────────────
    def apply_all(self, *, mode: str, effects: dict[str, Any],
                  enable_blur: bool = True) -> None:
        self.apply_fonts()
        self.apply_appearance(mode)
        self.apply_sections()
        self.apply_dock(icon_size=effects.get("dock_icon_size"), mode=mode)
        self.apply_nautilus()
        self.apply_desktop_icons()
        self.apply_keybindings()
        self.apply_spotlight()
        self.apply_favorites()
        self.apply_blur(mode=mode)
        self.apply_widgets()
        self.apply_ptyxis()
        if self.failed:
            log.warning("%d setting(s) could not be applied: %s",
                        len(self.failed), ", ".join(self.failed))
