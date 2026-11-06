"""Persistent installation state, change journal and resumability."""
from __future__ import annotations

import getpass
import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import utilities as u

log = logging.getLogger("engine")

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, root: Path):
        self.root = Path(root) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.installation: dict[str, Any] = self._load("installation.json", {
            "schema_version": SCHEMA_VERSION,
            "project": "macos-tahoe-ubuntu",
            "created_at": _now(),
            "phases": {},
            "completed_phases": [],
            "failed_phases": [],
            "resume_required": False,
            "dry_run": False,
            "profile": None,
            "mode": None,
            "machine": {"hostname": socket.gethostname(), "user": getpass.getuser()},
        })
        self.components: dict[str, Any] = self._load("component-status.json", {"components": {}})
        self.settings: dict[str, Any] = self._load("applied-settings.json", {"settings": {}})
        self.packages: dict[str, Any] = self._load("installed-packages.json", {"packages": []})
        self.extensions: dict[str, Any] = self._load("installed-extensions.json", {"extensions": {}})
        self.checksums: dict[str, Any] = self._load("checksums.json", {"assets": {}})
        self._reconcile_phases()

    def _path(self, name: str) -> Path:
        return self.root / name

    def _load(self, name: str, default: dict) -> dict:
        data = u.read_json(self._path(name), required=False)
        if data is None:
            return default
        if not isinstance(data, dict):
            raise u.ConfigError(f"state file {name} is not a JSON object")
        return data

    # ── phases ────────────────────────────────────────────────────────────
    def begin_fresh_run(self) -> None:
        """Clear phase bookkeeping for a new (non-resume) installation.

        History and backups are kept; only the transaction state is reset.
        """
        self.installation.update({
            "phases": {}, "completed_phases": [], "failed_phases": [],
            "resume_required": False, "backup_dir": None,
        })
        self.installation.pop("completed_at", None)
        self.installation.pop("uninstalled_at", None)
        self.save()

    def start_phase(self, name: str) -> None:
        entry = self.installation["phases"].get(name, {})
        entry.update({"status": "running", "started_at": _now()})
        entry.pop("error", None)
        self.installation["phases"][name] = entry
        self.save()

    def finish_phase(self, name: str, *, skipped: bool = False) -> None:
        entry = self.installation["phases"].setdefault(name, {})
        entry.update({"status": "skipped" if skipped else "ok", "finished_at": _now()})
        entry.pop("error", None)
        if name not in self.installation["completed_phases"]:
            self.installation["completed_phases"].append(name)
        if name in self.installation["failed_phases"]:
            self.installation["failed_phases"].remove(name)
        self.installation["resume_required"] = bool(self.installation["failed_phases"])
        self.save()

    def fail_phase(self, name: str, error: str) -> None:
        entry = self.installation["phases"].setdefault(name, {})
        entry.update({"status": "failed", "finished_at": _now(), "error": error})
        if name not in self.installation["failed_phases"]:
            self.installation["failed_phases"].append(name)
        self.installation["resume_required"] = True
        self.save()

    def phase_done(self, name: str) -> bool:
        return name in self.installation.get("completed_phases", [])

    def _reconcile_phases(self) -> None:
        for name, entry in self.installation.get("phases", {}).items():
            if entry.get("status") == "running":
                entry["status"] = "interrupted"
                entry["finished_at"] = _now()
                if name not in self.installation["failed_phases"]:
                    self.installation["failed_phases"].append(name)
                self.installation["resume_required"] = True

    # ── metadata ──────────────────────────────────────────────────────────
    def set_run(self, *, profile: str, mode: str, dry_run: bool) -> None:
        self.installation.update({"profile": profile, "mode": mode,
                                  "dry_run": dry_run, "updated_at": _now()})
        self.save()

    def complete(self) -> None:
        self.installation.update({"completed_at": _now(), "resume_required": False,
                                  "updated_at": _now()})
        self.save()

    # ── components / settings / packages / extensions ─────────────────────
    def set_component(self, name: str, status: str, **detail: Any) -> None:
        entry = self.components.setdefault("components", {}).setdefault(name, {})
        entry.update({"status": status, "updated_at": _now(), **detail})
        self._save("component-status.json", self.components)

    def record_setting(self, schema: str, key: str, before: str | None,
                       after: str | None, schemadir: Path | None = None) -> None:
        ident = f"{schemadir or ''}|{schema}|{key}"
        store = self.settings.setdefault("settings", {})
        if ident not in store:
            store[ident] = {
                "schema": schema, "key": key,
                "schemadir": str(schemadir) if schemadir else None,
                "before": before, "applied_at": _now(),
            }
        store[ident]["after"] = after
        store[ident]["last_applied_at"] = _now()
        self._save("applied-settings.json", self.settings)

    def get_original(self, schema: str, key: str, schemadir: Path | None = None) -> tuple[bool, str | None]:
        ident = f"{schemadir or ''}|{schema}|{key}"
        entry = self.settings.get("settings", {}).get(ident)
        if not entry:
            return False, None
        return True, entry.get("before")

    def record_package(self, package: str, version: str, method: str) -> None:
        packages = self.packages.setdefault("packages", [])
        for entry in packages:
            if entry.get("package") == package:
                entry.update({"version": version, "method": method, "updated_at": _now()})
                break
        else:
            packages.append({"package": package, "version": version,
                             "method": method, "installed_at": _now()})
        self._save("installed-packages.json", self.packages)

    def record_extension(self, uuid: str, **detail: Any) -> None:
        self.extensions.setdefault("extensions", {})[uuid] = {
            **detail, "updated_at": _now()}
        self._save("installed-extensions.json", self.extensions)

    def record_asset(self, name: str, sha256: str, path: str) -> None:
        self.checksums.setdefault("assets", {})[name] = {
            "sha256": sha256, "path": path, "verified_at": _now()}
        self._save("checksums.json", self.checksums)

    def save(self) -> None:
        self.installation["updated_at"] = _now()
        self._save("installation.json", self.installation)

    def _save(self, name: str, data: dict) -> None:
        u.atomic_write_json(self._path(name), data)

    # ── summary ───────────────────────────────────────────────────────────
    def summary(self) -> dict[str, Any]:
        return {
            "profile": self.installation.get("profile"),
            "mode": self.installation.get("mode"),
            "completed_phases": len(self.installation.get("completed_phases", [])),
            "failed_phases": self.installation.get("failed_phases", []),
            "resume_required": self.installation.get("resume_required", False),
        }
