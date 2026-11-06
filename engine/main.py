#!/usr/bin/env python3
"""Command-line entry point for the macOS Tahoe Ubuntu engine."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Allow `python3 engine/main.py` while keeping package-relative imports.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine import (backup_manager, headless_test, installer, logger,
                        package_manager, rollback_manager, system_detect,
                        verifier)
    from engine import utilities as u
    from engine.state_manager import State
else:  # imported as a package (tests)
    from . import (backup_manager, headless_test, installer, logger,
                   package_manager, rollback_manager, system_detect, verifier)
    from . import utilities as u
    from .state_manager import State

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("engine")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tahoe-engine",
        description="Reproducible macOS Tahoe-inspired desktop for Ubuntu GNOME.")
    parser.add_argument("--profile", choices=("full", "lightweight", "visual-only",
                                              "repair"),
                        help="installation profile (default: hardware recommendation)")
    parser.add_argument("--dry-run", action="store_true",
                        help="describe every change without applying it")
    parser.add_argument("--offline", action="store_true",
                        help="use only bundled assets (no network)")
    parser.add_argument("--resume", action="store_true",
                        help="continue an interrupted installation")
    parser.add_argument("--restore", nargs="?", const="latest", metavar="BACKUP",
                        help="restore the pre-install configuration")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove components owned by this project")
    parser.add_argument("--verify", action="store_true",
                        help="verify the installation and exit")
    parser.add_argument("--repair", action="store_true",
                        help="diagnose and re-apply managed components")
    parser.add_argument("--headless", action="store_true",
                        help="also run the isolated nested GNOME Shell test")
    parser.add_argument("--diagnostics", action="store_true",
                        help="write a diagnostics report and exit")
    parser.add_argument("--allow-untested", action="store_true",
                        help="allow an untested Ubuntu point release / GNOME major")
    parser.add_argument("--force-unsupported", action="store_true",
                        help="override the compatibility gate (unsafe)")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output for --verify")
    return parser


def _print_verify(report, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        verifier.print_report(report)
    return 0 if report.ok() else 1


def _diagnostics(root: Path) -> int:
    system = system_detect.detect()
    report = {
        "system": system,
        "project": str(root),
        "state_files": {p.name: str(p) for p in (root / "state").glob("*.json")},
        "backups": [str(p) for p in backup_manager.list_backups(root)],
        "extensions_installed": {
            p.name for p in (u.data_home() / "gnome-shell/extensions").glob("*")
        } if (u.data_home() / "gnome-shell/extensions").is_dir() else set(),
        "spotlight": {
            "wrapper": str(Path.home() / ".local/bin/tahoe-spotlight"),
            "rofi_system": package_manager.installed("rofi"),
            "rofi_runtime": (root / "runtime/rofi/usr/bin/rofi").exists(),
        },
        "log_files": [str(p) for p in sorted((root / "logs").glob("*.log"))[-10:]],
    }
    report["extensions_installed"] = sorted(report["extensions_installed"])
    out = root / "reports/diagnostics.json"
    u.atomic_write_json(out, report)
    log.info("diagnostics written to %s", out)
    counts = {
        "installed extensions": len(report["extensions_installed"]),
        "backups": len(report["backups"]),
        "logs": len(report["log_files"]),
    }
    for key, value in counts.items():
        log.info("%s: %s", key, value)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_path = None
    try:
        _, log_path = logger.setup_logging(ROOT / "logs", verbose=args.verbose)
        if args.verify:
            system = system_detect.detect()
            state = State(ROOT)
            report = verifier.verify(ROOT, state, system)
            out = ROOT / "reports/verification.json"
            extra = {}
            if args.headless:
                log.info("starting isolated headless GNOME Shell")
                shot = ROOT / "reports/headless-dark.png"
                result = headless_test.run(ROOT, screenshot=shot)
                u.atomic_write_json(ROOT / "reports/headless-result.json", result)
                extra["headless"] = {k: result.get(k) for k in
                                     ("ok", "states", "error", "screenshot")}
                if result.get("ok"):
                    log.info("headless shell: extensions ACTIVE (%s)", result["states"])
                else:
                    log.warning("headless shell check did not pass: %s (%s)",
                                result.get("error") or "not active",
                                result.get("states"))
            verifier.save_report(report, out, extra=extra)
            rc = _print_verify(report, args.json)
            if args.headless and not extra.get("headless", {}).get("ok"):
                rc = 1
            return rc
        if args.diagnostics:
            return _diagnostics(ROOT)
        if args.restore:
            engine = installer.Installer(ROOT, args)
            engine.preflight()
            return engine.restore(None if args.restore == "latest" else args.restore)
        if args.uninstall:
            state = State(ROOT)
            result = rollback_manager.uninstall(
                ROOT, state, backup_dir=backup_manager.latest_backup(ROOT),
                dry_run=args.dry_run, restore_backup=True)
            log.info("removed %d managed paths; restored %d settings",
                     len(result["files_removed"]), len(result["settings_restored"]))
            log.info("log out and back in to finish returning to the previous desktop")
            return 0
        if args.repair:
            system = system_detect.detect()
            state = State(ROOT)
            report = verifier.verify(ROOT, state, system)
            verifier.print_report(report)
            if report.ok() and not args.headless:
                log.info("no managed problems found; nothing to repair")
                return 0
            args.profile = "repair"
        engine = installer.Installer(ROOT, args)
        return engine.run()
    except KeyboardInterrupt:
        log.error("interrupted by user; state has been saved — resume with --resume")
        return 130
    except u.EngineError as exc:
        log.error("%s", exc)
        if log_path:
            log.error("full log: %s", log_path)
        return 1
    finally:
        logger.close_logging()


if __name__ == "__main__":
    raise SystemExit(main())
