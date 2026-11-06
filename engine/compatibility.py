"""Compatibility evaluation and hardware profile selection."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import utilities as u

log = logging.getLogger("engine")


@dataclass
class CompatResult:
    status: str                     # validated | untested | unsupported
    profile_id: str | None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_profile: str = "full"
    effects: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "validated"


def load_supported(root: Path) -> dict[str, Any]:
    return u.read_json(root / "manifests/supported-systems.json")


def load_hardware_profiles(root: Path) -> dict[str, Any]:
    return u.read_json(root / "config/hardware-profiles.json")


def _profile_matches(profile: dict, system: dict) -> bool:
    osr = system["os"]
    desktop = system["desktop"]
    if profile.get("distribution") != osr.get("id"):
        return False
    if profile.get("release") != osr.get("version_id"):
        return False
    if profile.get("gnome_major") != desktop.get("gnome_major"):
        return False
    sessions = profile.get("sessions") or []
    if sessions and desktop.get("session") not in sessions:
        return False
    return True


def _pick_hardware_rule(system: dict, profiles: dict) -> dict:
    gpu_text = " ".join(
        [system["hardware"]["gpu"].get("renderer") or ""]
        + system["hardware"]["gpu"].get("names", [])
    )
    ram = system["hardware"].get("ram_mb") or 0
    for rule in profiles.get("rules", []):
        if rule.get("id") == "default":
            continue
        terms = rule.get("match_gpu") or []
        if terms and any(t.lower() in gpu_text.lower() for t in terms):
            return rule
        max_ram = rule.get("match_max_ram_mb")
        if max_ram and ram and ram <= max_ram:
            return rule
    for rule in profiles.get("rules", []):
        if rule.get("id") == "default":
            return rule
    return {"recommended_profile": "full", "effects": {}}


def evaluate(root: Path, system: dict, *, allow_untested: bool = False,
             force_unsupported: bool = False) -> CompatResult:
    supported = load_supported(root)
    hw_profiles = load_hardware_profiles(root)
    reasons: list[str] = []
    warnings: list[str] = []

    osr = system["os"]
    desktop = system["desktop"]
    if osr.get("id") != "ubuntu":
        reasons.append(f"distribution {osr.get('id')!r} is not Ubuntu")

    matched = next((p for p in supported.get("profiles", []) if _profile_matches(p, system)), None)
    if matched:
        status = "validated"
        profile_id = matched["id"]
    else:
        same_major = any(p.get("gnome_major") == desktop.get("gnome_major")
                         for p in supported.get("profiles", []))
        if osr.get("id") == "ubuntu" and same_major:
            status = "untested"
            profile_id = None
            warnings.append(
                "Ubuntu release/session combination has not been validated "
                f"(detected {osr.get('version_id')} / GNOME {desktop.get('gnome_major')}).")
        else:
            status = "unsupported"
            profile_id = None
            reasons.append(
                f"GNOME {desktop.get('gnome_major')} on {osr.get('pretty_name')} is outside "
                "the validated support matrix.")

    reqs = supported.get("requirements", {})
    ram = system["hardware"].get("ram_mb") or 0
    if ram and ram < reqs.get("min_ram_mb", 0):
        reasons.append(f"only {ram} MB RAM (minimum {reqs.get('min_ram_mb')} MB)")
    free = system["hardware"]["disk_home"].get("free_mb") or 0
    if free and free < reqs.get("min_free_disk_mb", 0):
        reasons.append(f"only {free} MB free disk (minimum {reqs['min_free_disk_mb']} MB)")

    for cmd in reqs.get("required_commands", []):
        if not system["tools"].get(cmd):
            reasons.append(f"required command missing: {cmd}")
    for schema in reqs.get("required_schemas", []):
        if not u.gsettings_schema_exists(schema):
            reasons.append(f"required GSettings schema missing: {schema}")

    if desktop.get("session") not in ("wayland", "x11"):
        warnings.append(f"unknown session type: {desktop.get('session')!r}")

    rule = _pick_hardware_rule(system, hw_profiles)
    recommended = rule.get("recommended_profile", "full")
    effects = rule.get("effects", {})

    if reasons:
        status = "unsupported"
    if status == "untested" and not allow_untested:
        reasons.append("untested system: re-run with --allow-untested after reviewing the report")
        status = "unsupported"
    if status == "unsupported" and force_unsupported:
        warnings.append("continuing on an unsupported system because --force-unsupported was given")
        status = "untested"
    if status == "unsupported" and not reasons:
        reasons.append("system is not in the validated support matrix")

    return CompatResult(status=status, profile_id=profile_id, reasons=reasons,
                        warnings=warnings, recommended_profile=recommended,
                        effects=effects)


def extension_supported(metadata: dict, gnome_major: int | None) -> tuple[bool, str]:
    if gnome_major is None:
        return False, "GNOME major version unknown"
    versions = metadata.get("shell-version") or []
    if str(gnome_major) in [str(v) for v in versions]:
        return True, f"metadata lists GNOME {gnome_major}"
    return False, (f"metadata shell-version {versions} does not include GNOME {gnome_major}; "
                   "refusing to modify extension metadata")


def read_zip_metadata(archive: Path) -> dict:
    import zipfile
    try:
        with zipfile.ZipFile(archive) as zf:
            with zf.open("metadata.json") as fh:
                return json.loads(fh.read().decode("utf-8"))
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise u.ConfigError(f"invalid extension archive {archive}: {exc}") from exc
