"""Install, verify and enable GNOME Shell extensions without metadata hacks."""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from . import compatibility
from . import utilities as u

log = logging.getLogger("engine")


def user_extension_dir() -> Path:
    return u.data_home() / "gnome-shell/extensions"


def installed(uuid: str) -> bool:
    return (user_extension_dir() / uuid).is_dir() or \
        (Path("/usr/share/gnome-shell/extensions") / uuid).is_dir()


def metadata(uuid: str) -> dict | None:
    for root in (user_extension_dir(), Path("/usr/share/gnome-shell/extensions")):
        path = root / uuid / "metadata.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _compile_schemas(tree: Path) -> None:
    """Compile GSettings schemas shipped by an extension (EGO zips omit the
    compiled database, so gsettings --schemadir would otherwise fail)."""
    schemas = tree / "schemas"
    if not schemas.is_dir() or not any(schemas.glob("*.gschema.xml")):
        return
    compiler = u.which("glib-compile-schemas")
    if not compiler:
        raise u.EngineError("glib-compile-schemas is required to install extensions "
                            "with GSettings schemas")
    u.run([compiler, "--strict", str(schemas)], timeout=60)


def _validate_tree(tree: Path, expected_uuid: str, gnome_major: int) -> dict:
    meta_path = tree / "metadata.json"
    if not meta_path.exists():
        raise u.IntegrityError(f"extension archive has no metadata.json: {tree.name}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise u.IntegrityError(f"invalid extension metadata: {exc}") from exc
    if meta.get("uuid") != expected_uuid:
        raise u.IntegrityError(
            f"extension UUID mismatch: expected {expected_uuid}, got {meta.get('uuid')}")
    ok, reason = compatibility.extension_supported(meta, gnome_major)
    if not ok:
        raise u.EngineError(f"{expected_uuid}: {reason}")
    return meta


def install_zip(archive: Path, expected_uuid: str, gnome_major: int,
                *, dry_run: bool = False) -> dict:
    meta = compatibility.read_zip_metadata(archive)
    if meta.get("uuid") != expected_uuid:
        raise u.IntegrityError(f"UUID mismatch in {archive}")
    ok, reason = compatibility.extension_supported(meta, gnome_major)
    if not ok:
        raise u.EngineError(f"{expected_uuid}: {reason}")
    dest = user_extension_dir() / expected_uuid
    if dry_run:
        log.info("[dry-run] would install extension %s v%s", expected_uuid, meta.get("version"))
        return meta
    with tempfile.TemporaryDirectory(prefix="tahoe-ext-") as tmp:
        u.safe_extract_zip(archive, Path(tmp))
        tree = Path(tmp)
        if not (tree / "metadata.json").exists():
            children = [c for c in tree.iterdir() if c.is_dir()]
            if len(children) == 1:
                tree = children[0]
        _validate_tree(tree, expected_uuid, gnome_major)
        _compile_schemas(tree)
        u.copy_tree_atomic(tree, dest)
    return meta


def install_dir(source: Path, expected_uuid: str, gnome_major: int,
                *, dry_run: bool = False) -> dict:
    source = Path(source)
    meta = _validate_tree(source, expected_uuid, gnome_major)
    dest = user_extension_dir() / expected_uuid
    if dry_run:
        log.info("[dry-run] would install extension %s (bundled)", expected_uuid)
        return meta
    _compile_schemas(source)
    u.copy_tree_atomic(source, dest)
    return meta


def _get_enabled() -> list[str]:
    return u.gsettings_array(u.gsettings_get("org.gnome.shell", "enabled-extensions"))


def _get_disabled() -> list[str]:
    return u.gsettings_array(u.gsettings_get("org.gnome.shell", "disabled-extensions"))


def enable(uuid: str, *, dry_run: bool = False) -> None:
    if dry_run:
        log.info("[dry-run] would enable extension %s", uuid)
        return
    enabled = _get_enabled()
    disabled = _get_disabled()
    changed = False
    if uuid not in enabled:
        enabled.append(uuid)
        u.gsettings_set("org.gnome.shell", "enabled-extensions", enabled)
        changed = True
    if uuid in disabled:
        disabled = [d for d in disabled if d != uuid]
        u.gsettings_set("org.gnome.shell", "disabled-extensions", disabled)
        changed = True
    proc = u.run(["gsettings", "get", "org.gnome.shell", "disable-user-extensions"],
                 check=False, timeout=20)
    if "true" in (proc.stdout or ""):
        u.gsettings_set("org.gnome.shell", "disable-user-extensions", False)
        changed = True
    if changed:
        log.info("enabled extension %s", uuid)


def disable(uuid: str, *, dry_run: bool = False) -> None:
    """Disable an extension, including one force-enabled by the Ubuntu session.

    Ubuntu's session mode JSON force-enables ubuntu-dock; removing it from
    enabled-extensions is not enough. It must also be listed in
    disabled-extensions so the Shell does not load it.
    """
    enabled = _get_enabled()
    disabled = _get_disabled()
    changed = False
    if uuid in enabled:
        enabled = [e for e in enabled if e != uuid]
        changed = True
    if uuid not in disabled:
        disabled.append(uuid)
        changed = True
    if not changed:
        return
    if dry_run:
        log.info("[dry-run] would disable extension %s", uuid)
        return
    u.gsettings_set("org.gnome.shell", "enabled-extensions", enabled)
    u.gsettings_set("org.gnome.shell", "disabled-extensions", disabled)
    log.info("disabled extension %s", uuid)


def _shell_on_bus() -> bool:
    proc = u.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                  "--object-path", "/org/freedesktop/DBus", "--method",
                  "org.freedesktop.DBus.NameHasOwner", "org.gnome.Shell"],
                 check=False, timeout=10)
    return proc.returncode == 0 and "true" in (proc.stdout or "").lower()


def shell_state(uuid: str) -> str | None:
    if not _shell_on_bus():
        return None
    proc = u.run(["gnome-extensions", "info", uuid], check=False, timeout=20)
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if line.strip().startswith("State:"):
            return line.split(":", 1)[1].strip()
    return None


def remove(uuid: str, *, dry_run: bool = False) -> None:
    path = user_extension_dir() / uuid
    if not path.exists():
        return
    if dry_run:
        log.info("[dry-run] would remove extension %s", uuid)
        return
    u.remove_path(path)
    enabled = [e for e in _get_enabled() if e != uuid]
    u.gsettings_set("org.gnome.shell", "enabled-extensions", enabled)
    log.info("removed extension %s", uuid)


def disable_conflicting_docks(conflicts: list[str], *, dry_run: bool = False) -> list[str]:
    """Keep exactly one dock. Ubuntu Dock wins; a competing dock is disabled."""
    disabled: list[str] = []
    for uuid in conflicts:
        if uuid == "ubuntu-dock@ubuntu.com":
            continue
        if uuid in _get_enabled():
            disable(uuid, dry_run=dry_run)
            disabled.append(uuid)
    return disabled
