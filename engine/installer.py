"""Installation orchestration: preflight → backup → assets → configuration."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from . import (app_manager, backup_manager, compatibility, desktop_config,
               extension_manager, headless_test, package_manager, performance,
               rollback_manager, system_detect, theme_manager, verifier)
from . import utilities as u
from .state_manager import State

log = logging.getLogger("engine")

PROJECT_VERSION = "1.1.1"
PROFILES = ("full", "lightweight", "visual-only", "repair")

PHASES = ["backup", "assets", "extensions", "spotlight", "desktop", "apps",
          "verify", "report"]


class Installer:
    def __init__(self, root: Path, args: Any):
        self.root = Path(root)
        self.args = args
        self.dry_run = bool(getattr(args, "dry_run", False))
        self.offline = bool(getattr(args, "offline", False))
        self.resume = bool(getattr(args, "resume", False))
        self.headless = bool(getattr(args, "headless", False))
        self.state = State(root)
        self.system: dict[str, Any] = {}
        self.compat = None
        self.profile = "full"
        self.effects: dict[str, Any] = {}
        self.backup_dir: Path | None = None
        self.baseline: dict[str, Any] | None = None
        self.final_perf: dict[str, Any] | None = None
        self.verification = None

    # ── preflight ─────────────────────────────────────────────────────────
    def preflight(self) -> None:
        log.info("inspecting the system")
        self.system = system_detect.detect()
        self.compat = compatibility.evaluate(
            self.root, self.system,
            allow_untested=bool(getattr(self.args, "allow_untested", False)),
            force_unsupported=bool(getattr(self.args, "force_unsupported", False)))
        desktop = self.system["desktop"]
        hw = self.system["hardware"]
        log.info("%s • GNOME %s • %s • %s", self.system["os"]["pretty_name"],
                 desktop.get("gnome_shell"), desktop.get("session"),
                 desktop.get("resolution") or "unknown resolution")
        log.info("%s, %s MB RAM, GPU: %s", hw.get("cpu"), hw.get("ram_mb"),
                 "; ".join(hw["gpu"].get("names") or [hw["gpu"].get("renderer") or "unknown"]))
        for warning in self.compat.warnings:
            log.warning(warning)
        if self.compat.reasons:
            for reason in self.compat.reasons:
                log.error(reason)
            raise u.EngineError(
                "this system is not supported; nothing has been changed. "
                "See docs/reports/COMPATIBILITY_REPORT.md for details.")
        log.info("compatibility: %s", self.compat.status)

        self.profile = self._resolve_profile()
        self.effects = self.compat.effects or {}
        log.info("profile: %s", self.profile)
        self._write_audit_reports()

    def _resolve_profile(self) -> str:
        requested = getattr(self.args, "profile", None)
        if requested == "repair":
            stored = self.state.installation.get("profile")
            log.info("repair mode: reusing profile %r", stored)
            return stored if stored in ("full", "lightweight", "visual-only") \
                else self.compat.recommended_profile
        if requested:
            if requested not in PROFILES:
                raise u.EngineError(f"unknown profile: {requested}")
            return requested
        return self.compat.recommended_profile

    # ── phases ────────────────────────────────────────────────────────────
    def run(self) -> int:
        self.preflight()
        if self.resume:
            self._validate_resume()
            if self.state.installation.get("dry_run"):
                log.info("previous state was a dry run; starting a real installation")
                self.state.begin_fresh_run()
        elif not self.dry_run and not getattr(self.args, "repair", False):
            self.state.begin_fresh_run()
        self.state.set_run(profile=self.profile,
                           mode="offline" if self.offline else "online",
                           dry_run=self.dry_run)

        for phase in PHASES:
            if self.resume and self.state.phase_done(phase):
                log.info("resume: skipping completed phase %s", phase)
                continue
            self.state.start_phase(phase)
            try:
                getattr(self, f"phase_{phase}")()
            except Exception as exc:
                detail = str(exc)
                self.state.fail_phase(phase, detail)
                log.error("phase %s failed: %s", phase, detail)
                if not self.dry_run:
                    self._recover(phase, exc)
                raise
            else:
                self.state.finish_phase(phase)
        self.state.complete()
        self._print_next_steps()
        return 0

    def _validate_resume(self) -> None:
        machine = self.state.installation.get("machine", {})
        if machine.get("hostname") not in (None, self.system["user"]["hostname"]):
            raise u.EngineError(
                f"state belongs to host {machine.get('hostname')!r}, not this machine; "
                "refusing to resume. Use --restore or start a fresh installation.")
        if not self.state.installation.get("resume_required") and not self.state.installation.get("completed_phases"):
            log.info("nothing to resume; running a normal installation")

    def _recover(self, phase: str, exc: Exception) -> None:
        """Undo settings applied during this failed transaction when safe."""
        try:
            if phase in ("desktop", "verify", "report") and self.state.settings.get("settings"):
                log.warning("rolling back settings changed by this installation")
                rollback_manager.restore_managed_settings(self.state)
        except Exception as rollback_exc:  # never mask the original error
            log.error("automatic rollback failed: %s", rollback_exc)

    # ── individual phases ─────────────────────────────────────────────────
    def phase_backup(self) -> None:
        if self.dry_run:
            log.info("[dry-run] would create a timestamped backup in backups/")
            return
        pristine = self.state.installation.get("pristine_backup")
        if pristine and Path(pristine).exists():
            self.backup_dir = Path(pristine)
            log.info("reusing the original pre-install backup: %s", self.backup_dir)
            self.baseline = self._load_baseline()
            return
        log.info("capturing baseline performance (3 s sample)")
        self.baseline = performance.snapshot(3.0)
        self.backup_dir = backup_manager.create_backup(self.root, "pre-install")
        ok, problems = backup_manager.verify_backup(self.backup_dir)
        if not ok:
            raise u.EngineError("backup verification failed: " + "; ".join(problems))
        self.state.installation["backup_dir"] = str(self.backup_dir)
        self.state.installation.setdefault("pristine_backup", str(self.backup_dir))
        self.state.save()
        u.atomic_write_json(self.root / "reports/baseline-performance.json", self.baseline)
        log.info("baseline: %s MB used, shell %s MB / %s%% CPU, %s processes",
                 self.baseline["ram_used_mb"],
                 (self.baseline.get("gnome_shell") or {}).get("rss_mb"),
                 (self.baseline.get("gnome_shell") or {}).get("cpu_pct"),
                 self.baseline["process_count"])

    def _load_baseline(self) -> dict | None:
        path = self.root / "reports/baseline-performance.json"
        return u.read_json(path, required=False)

    def phase_assets(self) -> None:
        self._ensure_apple_wallpapers()
        self._verify_assets()
        mode = self._current_mode()
        theme_manager.install_themes(self.root, dry_run=self.dry_run)
        theme_manager.install_gtk_layers(self.root, mode=mode, dry_run=self.dry_run)
        theme_manager.install_icons(self.root, dry_run=self.dry_run)
        theme_manager.install_cursors(self.root, dry_run=self.dry_run)
        theme_manager.install_fonts(self.root, dry_run=self.dry_run)
        theme_manager.install_wallpapers(self.root, dry_run=self.dry_run)
        theme_manager.install_rofi_theme(self.root, dry_run=self.dry_run)
        theme_manager.install_ptyxis_palette(self.root, dry_run=self.dry_run)
        theme_manager.install_appearance_runtime(self.root, mode=mode,
                                                 dry_run=self.dry_run)
        app_manager.install_trash(dry_run=self.dry_run)
        self.state.set_component("assets", "installed", mode=mode)

    def _ensure_apple_wallpapers(self) -> None:
        """Fetch the pinned Apple wallpapers in online mode when absent."""
        manifest = u.read_json(self.root / "manifests/assets.json")["assets"]
        wanted = [(name, asset) for name, asset in manifest.items()
                  if asset.get("proprietary") and asset.get("url")]
        if not wanted:
            return
        cache = self.root / "assets/wallpapers/apple"
        cache.mkdir(parents=True, exist_ok=True)
        from .downloader import Downloader
        downloader = Downloader(cache, offline=self.offline)
        for name, asset in wanted:
            path = self.root / asset["local"]
            if path.exists():
                continue
            filename = Path(asset["local"]).name
            if self.dry_run:
                log.info("[dry-run] would download %s", name)
                continue
            try:
                downloader.fetch(asset["url"], filename=filename,
                                 sha256=asset.get("sha256"), required=False)
            except (u.EngineError, u.IntegrityError) as exc:
                log.warning("could not fetch %s: %s", name, exc)

    def _verify_assets(self) -> None:
        manifest = u.read_json(self.root / "manifests/assets.json")
        for name, asset in manifest["assets"].items():
            local = self.root / asset["local"]
            if not local.exists():
                if asset.get("proprietary"):
                    log.warning("proprietary asset unavailable: %s (fallback will be used)", name)
                    continue
                raise u.IntegrityError(f"missing bundled asset {name}: {local}")
            expected = asset.get("sha256")
            if expected and expected not in ("PENDING", "computed-at-install"):
                digest = u.sha256_file(local)
                if digest != expected:
                    raise u.IntegrityError(
                        f"asset {name} checksum mismatch (expected {expected}, got {digest})")
                self.state.record_asset(name, digest, str(local))
            elif asset.get("kind") == "file":
                self.state.record_asset(name, u.sha256_file(local), str(local))
        log.info("asset integrity verified")

    def phase_extensions(self) -> None:
        if self.profile == "visual-only":
            log.info("visual-only profile: GNOME extensions are left untouched")
            return
        major = self.system["desktop"]["gnome_major"]
        desktop = u.read_json(self.root / "config/desktop.json")
        cache = self.root / "assets/cache/extensions"

        extension_manager.disable_conflicting_docks(
            desktop["extensions"]["conflicting_docks"], dry_run=self.dry_run)

        # User Themes, the TPCT global-menu extension, Blur my Shell, MacOSDock.
        meta = extension_manager.install_zip(
            cache / "user-theme@gnome-shell-extensions.gcampax.github.com.shell-extension.zip",
            "user-theme@gnome-shell-extensions.gcampax.github.com", major,
            dry_run=self.dry_run)
        self.state.record_extension(
            "user-theme@gnome-shell-extensions.gcampax.github.com",
            version=meta.get("version"), method="bundled-zip")

        meta = extension_manager.install_dir(
            self.root / "extensions/tpct-mac-shell@tpct", "tpct-mac-shell@tpct",
            major, dry_run=self.dry_run)
        self.state.record_extension("tpct-mac-shell@tpct", version=meta.get("version"),
                                    method="bundled-directory")

        meta = extension_manager.install_zip(
            cache / "blur-my-shell@aunetx.shell-extension.zip",
            "blur-my-shell@aunetx", major, dry_run=self.dry_run)
        self.state.record_extension("blur-my-shell@aunetx",
                                    version=meta.get("version"), method="bundled-zip")

        meta = extension_manager.install_dir(
            self.root / "extensions/macos-dock@vinnytherobot.github.io",
            "macos-dock@vinnytherobot.github.io", major, dry_run=self.dry_run)
        self.state.record_extension("macos-dock@vinnytherobot.github.io",
                                    version=meta.get("version"), method="bundled-patched")

        for uuid in desktop["extensions"]["required"]:
            if extension_manager.installed(uuid):
                extension_manager.enable(uuid, dry_run=self.dry_run)
        for uuid in desktop["extensions"].get("ensure_enabled", []):
            if extension_manager.installed(uuid):
                extension_manager.enable(uuid, dry_run=self.dry_run)
        for uuid in desktop["extensions"].get("disable", []):
            extension_manager.disable(uuid, dry_run=self.dry_run)
        self.state.set_component("extensions", "installed",
                                 blur=True, dock="macos-dock")

    def phase_spotlight(self) -> None:
        if self.profile == "visual-only":
            return
        binary = package_manager.install_rofi_user(
            self.root, offline=self.offline, dry_run=self.dry_run)
        if binary is None:
            log.warning("Spotlight backend unavailable; Super+Space will not be bound")
            self.state.set_component("spotlight", "unavailable")
            return
        theme_manager.install_spotlight_wrapper(self.root, binary, dry_run=self.dry_run)
        self.state.set_component("spotlight", "installed", binary=str(binary))

    def phase_desktop(self) -> None:
        applier = desktop_config.ConfigApplier(
            self.root, self.state, dry_run=self.dry_run, profile=self.profile)
        mode = self._current_mode()
        if self.profile == "visual-only":
            applier.apply_fonts()
            applier.apply_appearance(mode)
            self.state.set_component("desktop", "applied", scope="visual-only")
            return
        applier.apply_all(mode=mode, effects=self.effects)
        if applier.failed:
            raise u.EngineError(
                "some desktop settings could not be applied: " + ", ".join(applier.failed))
        self.state.set_component("desktop", "applied", scope=self.profile)
        log.info("applied %d settings (%d already correct)",
                 len(applier.applied), len(applier.skipped))

    def _current_mode(self) -> str:
        raw = u.gsettings_get("org.gnome.desktop.interface", "color-scheme") or ""
        if "light" in raw:
            return "light"
        return "dark"

    def phase_apps(self) -> None:
        if self.profile == "visual-only":
            return
        app_manager.install(self.root, dry_run=self.dry_run)
        desktop = u.read_json(self.root / "config/desktop.json")
        if self.profile == "full":
            theme_manager.install_firefox(self.root, dry_run=self.dry_run)
        else:
            log.info("lightweight profile: Firefox chrome is not modified")
        desktop_config.ConfigApplier(
            self.root, self.state, dry_run=self.dry_run,
            profile=self.profile).start_appearance_daemon()
        self.state.set_component("apps", "configured",
                                 firefox=self.profile == "full")

    def phase_verify(self) -> None:
        wrapper = None
        if self.dry_run:
            log.info("[dry-run] skipping live verification")
            return
        report = verifier.verify(self.root, self.state, self.system,
                                 profile=self.profile,
                                 run_functional=(self.profile != "visual-only"))
        self.verification = report
        verifier.print_report(report)
        verifier.save_report(report, self.root / "reports/verification.json",
                             extra={"profile": self.profile,
                                    "candidates_checked": len(report.checks)})
        if not report.ok():
            names = ", ".join(c.name for c in report.failures)
            raise u.EngineError(f"verification failed: {names}")
        wrapper = Path.home() / ".local/bin/tahoe-spotlight"
        if self.headless:
            log.info("starting isolated headless GNOME Shell (no logout required)")
            shot = self.root / "reports/headless-dark.png"
            result = headless_test.run(self.root, screenshot=shot)
            u.atomic_write_json(self.root / "reports/headless-result.json", result)
            if result.get("ok"):
                log.info("headless shell: theme extensions ACTIVE (%s)", result["states"])
            else:
                log.warning("headless shell check: %s (states: %s)",
                            result.get("error") or "not active", result.get("states"))
                if result.get("errors"):
                    for line in result["errors"][:5]:
                        log.warning("headless: %s", line)
        self.state.set_component("verify", "passed",
                                 checks=len(report.checks))

    def phase_report(self) -> None:
        if not self.dry_run:
            log.info("measuring final performance (3 s sample)")
            self.final_perf = performance.snapshot(3.0)
            u.atomic_write_json(self.root / "reports/final-performance.json", self.final_perf)
        self._write_reports()
        self.state.set_component("report", "written")

    # ── reports ───────────────────────────────────────────────────────────
    def _write_audit_reports(self) -> None:
        reports = self.root / "docs/reports"
        reports.mkdir(parents=True, exist_ok=True)
        s = self.system
        hw = s["hardware"]
        lines = [
            "# Initial Audit", "",
            f"Generated: {s['timestamp']}", "",
            "## Operating system", "",
            f"- {s['os']['pretty_name']} ({s['os']['codename']})",
            f"- Kernel: {s['os']['kernel']} ({s['os']['arch']})",
            f"- Session: {s['desktop']['session']} / {s['desktop']['shell']}",
            f"- GNOME Shell: {s['desktop']['gnome_shell']}",
            f"- Resolution: {s['desktop']['resolution'] or 'unknown'}", "",
            "## Hardware", "",
            f"- {hw['vendor']} {hw['model']}",
            f"- CPU: {hw['cpu']} ({hw['cores']} threads)",
            f"- RAM: {hw['ram_mb']} MB",
            f"- GPU: {'; '.join(hw['gpu']['names']) or hw['gpu'].get('renderer') or 'unknown'} "
            f"(driver: {hw['gpu'].get('driver')})",
            f"- Disk: {hw['disk_home']['free_mb']} MB free of "
            f"{hw['disk_home']['total_mb']} MB on /home", "",
            "## Desktop state before changes", "",
            f"- GTK theme: {s['interface']['gtk-theme']}",
            f"- Icon theme: {s['interface']['icon-theme']}",
            f"- Cursor: {s['interface']['cursor-theme']}",
            f"- Font: {s['interface']['font-name']}",
            f"- Window buttons: {s['interface']['button-layout']}",
            f"- Wallpaper: {s['interface']['wallpaper']}", "",
            "### Enabled extensions", "",
        ]
        lines += [f"- `{uuid}`" for uuid in s["extensions"]["enabled"]]
        lines += ["", "### Dock", ""]
        for key, value in s["interface"]["dock"].items():
            lines.append(f"- {key}: {value}")
        audit_path = reports / "INITIAL_AUDIT.md"
        if not audit_path.exists():
            u.atomic_write_text(audit_path, "\n".join(lines) + "\n")

        compat_lines = [
            "# Compatibility Report", "",
            f"Generated: {s['timestamp']}", "",
            f"- Detected: {s['os']['pretty_name']} / GNOME "
            f"{s['desktop']['gnome_major']} / {s['desktop']['session']}",
            f"- Result: **{self.compat.status}**",
            f"- Matched profile: {self.compat.profile_id or 'none'}",
            f"- Recommended install profile: {self.compat.recommended_profile}", "",
            "## Reasons and warnings", "",
        ]
        compat_lines += [f"- {r}" for r in self.compat.reasons] or ["- none"]
        compat_lines += [f"- {w}" for w in self.compat.warnings] or []
        compat_lines += ["", "## Selected components", "",
                         "- TPCT Mac theme + tpct-mac-shell extension (GPL-3.0, GNOME 50 metadata)",
                         "- WhiteSur icon theme and WhiteSur cursors (GPL-3.0)",
                         "- Inter variable font (OFL-1.1)",
                         "- Blur my Shell (GPL-3.0) for real backdrop blur, statically cached",
                         "- MacOSDock (MIT, vendored + spring patch) as the single dock",
                         "- Rofi 2.0 as the Spotlight backend (MIT)",
                         "- Measured Tahoe light/dark palettes and wallpapers",
                         "", "## Rejected candidates", ""]
        ext_manifest = u.read_json(self.root / "config/extension-manifest.json")
        for item in ext_manifest.get("rejected", []):
            compat_lines.append(f"- **{item['candidate']}** — {item['reason']}")
        u.atomic_write_text(reports / "COMPATIBILITY_REPORT.md",
                            "\n".join(compat_lines) + "\n")

    def _write_reports(self) -> None:
        reports = self.root / "docs/reports"
        reports.mkdir(parents=True, exist_ok=True)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        phases = self.state.installation.get("phases", {})
        lines = ["# Installation Report", "", f"Generated: {now}", "",
                 f"- Profile: **{self.profile}**",
                 f"- Mode: {'offline' if self.offline else 'online'}",
                 f"- Dry run: {self.dry_run}",
                 f"- Backup: `{self.backup_dir or 'none'}`", "",
                 "## Phases", "", "| Phase | Status | Detail |", "|---|---|---|"]
        for name in PHASES:
            entry = phases.get(name, {})
            status = entry.get("status", "not run")
            if name == "report" and status == "running":
                status = "ok (writing this report)"
            lines.append(f"| {name} | {status} | {entry.get('error', '')} |")
        lines += ["", "## Components", ""]
        for name, entry in sorted(self.state.components.get("components", {}).items()):
            lines.append(f"- **{name}**: {entry.get('status')}")
        lines += ["", f"Applied settings: {len(self.state.settings.get('settings', {}))}",
                  f"Installed extensions recorded: "
                  f"{len(self.state.extensions.get('extensions', {}))}", ""]
        if self.verification:
            counts = self.verification.counts()
            lines += ["## Verification", "",
                      f"{counts['pass']} passed, {counts['warn']} warnings, "
                      f"{counts['fail']} failed, {counts['skip']} skipped.", ""]
        u.atomic_write_text(reports / "INSTALLATION_REPORT.md", "\n".join(lines) + "\n")

        if self.baseline and self.final_perf:
            b, f = self.baseline, self.final_perf
            rows = [
                ("RAM used", f"{b['ram_used_mb']} MB", f"{f['ram_used_mb']} MB"),
                ("gnome-shell RSS",
                 f"{(b.get('gnome_shell') or {}).get('rss_mb')} MB",
                 f"{(f.get('gnome_shell') or {}).get('rss_mb')} MB"),
                ("gnome-shell CPU",
                 f"{(b.get('gnome_shell') or {}).get('cpu_pct')} %",
                 f"{(f.get('gnome_shell') or {}).get('cpu_pct')} %"),
                ("Process count", str(b["process_count"]), str(f["process_count"])),
                ("gjs processes", str(b["gjs_processes"]), str(f["gjs_processes"])),
            ]
            perf = ["# Performance Sample (generated)", "", f"Generated: {now}", "",
                    "Measurements are real 3-second /proc samples taken on this machine.",
                    "The final sample is taken while the previous GNOME Shell session is",
                    "still running (new extensions activate after the next login), so the",
                    "extension delta appears after logging out and back in.", "",
                    "| Metric | Baseline | After install |", "|---|---|---|"]
            perf += [f"| {name} | {before} | {after} |" for name, before, after in rows]
            disk = performance.disk_usage([
                u.data_home() / "themes",
                u.data_home() / "icons",
                u.data_home() / "fonts",
                u.data_home() / "backgrounds",
                self.root,
            ])
            perf += ["", "## Disk usage", ""]
            perf += [f"- {path}: {size} MB" for path, size in disk.items()]
            u.atomic_write_text(reports / "PERFORMANCE_SAMPLE.md", "\n".join(perf) + "\n")

    def _print_next_steps(self) -> None:
        if self.dry_run:
            log.info("dry run complete — no changes were made")
            return
        log.info("installation complete")
        log.info("log out and back in (or reboot) so GNOME Shell loads the new "
                 "theme and the global-menu extension")
        log.info("after logging back in, run ./verify.sh to confirm the live state")

    # ── restore / uninstall entry points ──────────────────────────────────
    def restore(self, selector: str | None = None) -> int:
        backup = backup_manager.resolve_backup(self.root, selector)
        log.info("restoring configuration from %s", backup)
        if self.dry_run:
            log.info("[dry-run] would restore dconf and files from %s", backup)
            return 0
        result = rollback_manager.uninstall(self.root, self.state,
                                            backup_dir=backup, dry_run=False,
                                            restore_backup=True)
        backup_manager.restore_dconf(backup)
        log.info("restored %d settings, removed %d managed paths",
                 len(result["settings_restored"]), len(result["files_removed"]))
        log.info("log out and back in to return to the previous desktop")
        return 0
