"""Run an isolated, nested GNOME Shell to test the theme without logging out.

Nothing here touches the live session: a private XDG_CONFIG_HOME/data/cache
tree, a private D-Bus session and a separate Wayland display are used.  The
nested shell is started in headless mode with a virtual 1366x768 monitor.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import utilities as u

log = logging.getLogger("engine")

DEBUG_UUID = "tahoe-debug@tahoe"


def _setup_tree(root: Path, home: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="tahoe-headless-"))
    config = tmp / "config"
    data = tmp / "data"
    cache = tmp / "cache"
    for path in (config, data / "gnome-shell/extensions", data / "themes",
                 cache, data / "fonts", data / "backgrounds"):
        path.mkdir(parents=True, exist_ok=True)

    ext_dst = data / "gnome-shell/extensions"
    installed_root = u.data_home() / "gnome-shell/extensions"
    if installed_root.is_dir():
        for src in installed_root.iterdir():
            if src.is_dir() and not (ext_dst / src.name).exists():
                os.symlink(src, ext_dst / src.name)

    debug = ext_dst / DEBUG_UUID
    debug.mkdir()
    (debug / "metadata.json").write_text(json.dumps({
        "uuid": DEBUG_UUID, "name": "Tahoe test helper",
        "description": "Screenshot support for the isolated test shell",
        "shell-version": ["50"], "version": 1,
    }))
    (debug / "extension.js").write_text(
        "export default class TahoeDebug {\n"
        "    enable() {\n"
        "        if (global.context)\n"
        "            global.context.unsafe_mode = true;\n"
        "    }\n"
        "    disable() {}\n"
        "}\n")

    for variant in ("Dark", "Light"):
        src = u.data_home() / "themes" / f"TPCT-Mac-{variant}"
        if src.exists():
            os.symlink(src, data / "themes" / f"TPCT-Mac-{variant}")

    for path in (u.data_home() / "fonts",):
        if path.exists():
            for item in path.iterdir():
                os.symlink(item, data / "fonts" / item.name)

    for name in ("gtk-3.0", "gtk-4.0"):
        src = u.config_home() / name
        if src.exists():
            os.symlink(src, config / name)
    backgrounds = u.data_home() / "backgrounds"
    if backgrounds.exists():
        os.symlink(backgrounds, data / "backgrounds-home")
    applications = u.data_home() / "applications"
    if applications.is_dir():
        os.symlink(applications, data / "applications")
    widgets = u.config_home() / "tpct-mac/widgets.json"
    if widgets.exists():
        (config / "tpct-mac").mkdir(parents=True, exist_ok=True)
        shutil.copy2(widgets, config / "tpct-mac/widgets.json")
    return tmp


def _session_env(tmp: Path, address: str | None = None) -> dict[str, str]:
    env = {**os.environ}
    env.update({
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_DATA_HOME": str(tmp / "data"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
        "GSETTINGS_BACKEND": "dconf",
    })
    if address:
        env["DBUS_SESSION_BUS_ADDRESS"] = address
    return env


def _set(env: dict[str, str], schema: str, key: str, value: Any,
         schemadir: Path | None = None) -> None:
    import subprocess as sp
    argv = ["gsettings", *(["--schemadir", str(schemadir)] if schemadir else []),
            "set", schema, key, u.to_gvariant(value)]
    sp.run(argv, env=env, capture_output=True, text=True, timeout=30)


def run(root: Path, *, timeout: int = 90, screenshot: Path | None = None,
        dark: bool = True, launch: list[str] | None = None,
        launch_wait: float = 5.0, eval_js: str | None = None,
        eval_wait: float = 1.5, enabled_extensions: list[str] | None = None,
        extra_settings: list[tuple[str, str, Any]] | None = None,
        mirror_dconf: bool = False, keep: bool = False,
        state_uuids: list[str] | None = None,
        perf_seconds: float = 0.0) -> dict[str, Any]:
    if not shutil.which("gnome-shell") or not shutil.which("dbus-run-session"):
        return {"ok": False, "error": "gnome-shell or dbus-run-session unavailable"}
    tmp = _setup_tree(root, Path.home())
    addr_file = tmp / "bus-address"
    log_file = tmp / "shell.log"
    display = f"wayland-tahoe-test-{os.getpid()}"
    state: dict[str, Any] = {"ok": False, "tmp": str(tmp), "states": {}, "keep": keep}
    dump_file = tmp / "live-dconf.ini"
    if mirror_dconf:
        dump = u.run(["dconf", "dump", "/"], check=False, timeout=180)
        dump_file.write_text(dump.stdout or "", encoding="utf-8")
        state["mirrored_dconf"] = True

    base_env = _session_env(tmp)
    schemadir = (tmp / "data/gnome-shell/extensions/"
                 "user-theme@gnome-shell-extensions.gcampax.github.com/schemas")
    variant = "Dark" if dark else "Light"
    enabled = enabled_extensions or [
        DEBUG_UUID, "user-theme@gnome-shell-extensions.gcampax.github.com",
        "tpct-mac-shell@tpct", "ubuntu-dock@ubuntu.com", "ding@rastersoft.com"]

    def gs(args: list[str]) -> str:
        return "gsettings " + " ".join(shlex.quote(a) for a in args)

    settings_cmds = [
        gs(["set", "org.gnome.shell", "enabled-extensions", u.to_gvariant(enabled)]),
        gs(["set", "org.gnome.shell", "disable-user-extensions", "false"]),
        gs(["set", "org.gnome.shell", "welcome-dialog-last-shown-version", "999"]),
        gs(["set", "org.gnome.desktop.interface", "color-scheme",
            u.to_gvariant("prefer-dark" if dark else "prefer-light")]),
        gs(["set", "org.gnome.desktop.interface", "gtk-theme",
            u.to_gvariant(f"TPCT-Mac-{variant}")]),
        gs(["set", "org.gnome.desktop.interface", "icon-theme",
            u.to_gvariant(f"WhiteSur-{'dark' if dark else 'light'}")]),
        gs(["set", "org.gnome.desktop.interface", "cursor-theme", "'WhiteSur-cursors'"]),
        gs(["set", "org.gnome.desktop.interface", "font-name", "'Inter 10.5'"]),
        gs(["--schemadir", str(schemadir), "set",
            "org.gnome.shell.extensions.user-theme", "name",
            u.to_gvariant(f"TPCT-Mac-{variant}")]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "dock-position", "'BOTTOM'"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "extend-height", "false"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "dash-max-icon-size", "40"]),
        gs(["set", "org.gnome.desktop.wm.preferences", "button-layout",
            "'close,minimize,maximize:'"]),
        gs(["set", "org.gnome.desktop.background", "picture-uri",
            u.to_gvariant("file://" + str(u.data_home() / "backgrounds/"
                                          / "macos-tahoe"
                                          / f"tahoe-{'dark' if dark else 'light'}.jpg"))]),
        gs(["set", "org.gnome.desktop.background", "picture-uri-dark",
            u.to_gvariant("file://" + str(u.data_home() / "backgrounds/"
                                          / "macos-tahoe/tahoe-dark.jpg"))]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "autohide", "false"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "intellihide", "false"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "dock-fixed", "true"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "transparency-mode",
            "'FIXED'"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "background-opacity",
            "0.32"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "show-show-apps-button",
            "true"]),
        gs(["set", "org.gnome.shell.extensions.dash-to-dock", "running-indicator-style",
            "'DOTS'"]),
    ]
    for schema, key, value in (extra_settings or []):
        cmds = ["set", schema, key, u.to_gvariant(value)]
        # Locate a user-extension schema directory when the schema is not
        # available system-wide.
        if not u.gsettings_schema_exists(schema):
            for ext in (tmp / "data/gnome-shell/extensions").iterdir():
                sd = ext / "schemas"
                if not sd.is_dir():
                    continue
                probe = u.run(["gsettings", "--schemadir", str(sd),
                               "list-keys", schema], check=False, timeout=10)
                if probe.returncode == 0:
                    cmds = ["--schemadir", str(sd)] + cmds
                    break
        settings_cmds.append(gs(cmds))

    load = f'dconf load / < "{dump_file}"; ' if mirror_dconf else ""
    inner = (
        f'echo "$DBUS_SESSION_BUS_ADDRESS" > "{addr_file}"; ' + load
        + "; ".join(settings_cmds) + "; "
        + "exec gnome-shell --headless --virtual-monitor 1366x768 "
        + f"--wayland-display {display} --no-x11"
    )
    out = log_file.open("w")
    proc = subprocess.Popen(["dbus-run-session", "--", "bash", "-c", inner],
                            env=base_env, stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True)
    launched: list[subprocess.Popen] = []
    try:
        address = None
        for _ in range(120):
            if proc.poll() is not None:
                break
            if addr_file.exists() and addr_file.stat().st_size:
                address = addr_file.read_text().strip()
                break
            time.sleep(0.5)
        if not address:
            state.update(ok=False, error="nested shell did not start")
            return state
        env = _session_env(tmp, address)
        env["WAYLAND_DISPLAY"] = display
        env.pop("DISPLAY", None)
        ready = False
        for _ in range(120):
            if proc.poll() is not None:
                break
            probe = u.run(["gdbus", "call", "--session", "--dest",
                           "org.freedesktop.DBus", "--object-path",
                           "/org/freedesktop/DBus", "--method",
                           "org.freedesktop.DBus.NameHasOwner", "org.gnome.Shell"],
                          check=False, timeout=10, env=env)
            if probe.returncode == 0 and "true" in (probe.stdout or "").lower():
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            state.update(ok=False, error="nested shell did not become ready")
            return state

        uuids = tuple(state_uuids or (
            "user-theme@gnome-shell-extensions.gcampax.github.com",
            "tpct-mac-shell@tpct"))
        for attempt in range(20):
            for uuid in uuids:
                info = u.run(["gnome-extensions", "info", uuid], check=False,
                             timeout=20, env=env)
                text = info.stdout or ""
                match = re.search(r"State:\s*(\w+)", text)
                state["states"][uuid] = match.group(1) if match else "UNKNOWN"
            if all(v == "ACTIVE" for v in state["states"].values()):
                break
            time.sleep(0.5)

        if launch:
            app_out = (tmp / "app.log").open("w")
            launched.append(subprocess.Popen(launch, env=env, stdout=app_out,
                                             stderr=subprocess.STDOUT,
                                             start_new_session=True))
            time.sleep(launch_wait)
            state["launched"] = launch

        if eval_js:
            eval_result = u.run(["gdbus", "call", "--session", "--dest",
                                 "org.gnome.Shell", "--object-path",
                                 "/org/gnome/Shell", "--method",
                                 "org.gnome.Shell.Eval", eval_js],
                                check=False, timeout=15, env=env)
            state["eval"] = (eval_result.stdout or "").strip()
            time.sleep(eval_wait)

        if perf_seconds > 0 and proc.poll() is None:
            pg = u.run(["ps", "-eo", "pid,comm,args"], check=False, timeout=10)
            shell_pid = proc.pid
            for line in (pg.stdout or "").splitlines():
                fields = line.split(None, 2)
                if len(fields) >= 2 and fields[1] == "gnome-shell" and display in line:
                    try:
                        shell_pid = int(fields[0])
                    except ValueError:
                        pass
                    break
            state["shell_pid"] = shell_pid

            def sample():
                stat = Path(f"/proc/{shell_pid}/stat").read_text()
                close = stat.rfind(")")
                fields = stat[close + 2:].split()
                ticks = int(fields[11]) + int(fields[12])
                rss = 0
                for line in Path(f"/proc/{shell_pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                        break
                return ticks, rss
            t1, r1 = sample()
            started = time.time()
            time.sleep(perf_seconds)
            t2, r2 = sample()
            elapsed = max(0.001, time.time() - started)
            hz = os.sysconf("SC_CLK_TCK")
            state["perf"] = {
                "cpu_pct": round(100.0 * (t2 - t1) / hz / elapsed, 2),
                "rss_mb": round(r2 / 1024, 1),
                "seconds": round(elapsed, 2),
                "extensions": len(enabled),
            }

        theme_probe = u.run(["gsettings", "--schemadir", str(schemadir), "get",
                             "org.gnome.shell.extensions.user-theme", "name"],
                            check=False, timeout=10, env=env)
        state["theme_name"] = (theme_probe.stdout or "").strip()

        if screenshot:
            # Let startup notifications (e.g. unsafe-mode banner) auto-dismiss.
            time.sleep(6)
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            # Dismiss the test-only "unsafe mode" system notification if the
            # shell exposes it through Eval.
            for expr in ("Main.messageTray._bannerBin.hide()",
                         "imports.ui.main.messageTray._bannerBin.hide()"):
                u.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                       "--object-path", "/org/gnome/Shell", "--method",
                       "org.gnome.Shell.Eval", expr],
                      check=False, timeout=10, env=env)
            shot = u.run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
                          "--object-path", "/org/gnome/Shell/Screenshot",
                          "--method", "org.gnome.Shell.Screenshot.Screenshot",
                          "false", "false", str(screenshot)],
                         check=False, timeout=30, env=env)
            state["screenshot_result"] = ((shot.stdout or "").strip()
                                          + (shot.stderr or "").strip())
            state["screenshot"] = str(screenshot) if screenshot.exists() else None

        time.sleep(1)
        text = log_file.read_text(encoding="utf-8", errors="replace")
        errors = [line for line in text.splitlines()
                  if re.search(r"JS ERROR|Extension .*Error|ERROR", line)
                  and ("tpct" in line or "user-theme" in line or "blur" in line)]
        state["errors"] = errors
        state["ok"] = (all(v == "ACTIVE" for v in state["states"].values())
                       and not errors)
        return state
    finally:
        for child in launched:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        out.close()
        if not state.get("ok"):
            state["keep"] = True
        if not state.get("keep"):
            if state.get("screenshot"):
                state["log_excerpt"] = log_file.read_text(
                    encoding="utf-8", errors="replace")[-4000:]
            shutil.rmtree(tmp, ignore_errors=True)
