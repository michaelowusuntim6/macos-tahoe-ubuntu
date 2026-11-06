"""APT-aware package handling that never upgrades the system.

Only missing packages are considered.  Nothing here bypasses sudo: when a
package needs system installation and authentication is not already available,
the operation is skipped with an exact instruction for the user.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from . import utilities as u

log = logging.getLogger("engine")

ROFI_DEPS = [
    "rofi",
    "libxcb-cursor0",
    "libxcb-ewmh2",
    "libxcb-icccm4",
    "libxcb-xinerama0",
    "libxcb-util1",
    "libxcb-xkb1",
    "libxkbcommon-x11-0",
    "libxcb-image0",
    "libxcb-render-util0",
    "libstartup-notification0",
]


def installed(package: str) -> bool:
    proc = u.run(["dpkg-query", "-W", "-f=${Status}", package], check=False, timeout=20)
    return "install ok installed" in (proc.stdout or "")


def version_of(package: str) -> str | None:
    proc = u.run(["dpkg-query", "-W", "-f=${Version}", package], check=False, timeout=20)
    return (proc.stdout or "").strip() or None


def sudo_available() -> bool:
    proc = u.run(["sudo", "-n", "true"], check=False, timeout=10)
    return proc.returncode == 0


def try_install_system(packages: list[str], *, dry_run: bool = False) -> list[str]:
    """Install missing packages with APT if passwordless sudo exists.

    Interactive sudo is intentionally not attempted from the engine: captured
    output cannot host a password prompt.  install.sh tells the user the exact
    command instead.
    """
    missing = [p for p in packages if not installed(p)]
    if not missing:
        return []
    if dry_run:
        log.info("[dry-run] would install with apt: %s", " ".join(missing))
        return missing
    if not sudo_available():
        log.warning("cannot install system packages without authentication: %s",
                    " ".join(missing))
        log.warning("install manually with: sudo apt install %s", " ".join(missing))
        return []
    u.run(["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", *missing],
          timeout=600)
    for package in missing:
        if installed(package):
            log.info("installed %s %s", package, version_of(package))
    return missing


def _download_debs(packages: list[str], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    proc = u.run(["apt-get", "download", *packages], check=False, timeout=600, cwd=dest)
    if proc.returncode != 0:
        raise u.EngineError(
            "apt-get download failed; a working Ubuntu archive is required:\n"
            + (proc.stderr or proc.stdout or "").strip())
    return sorted(dest.glob("*.deb"))


def _bundled_debs(root: Path) -> list[Path]:
    """Return bundled .debs after verifying the archive checksum list."""
    apt_dir = Path(root) / "assets/cache/apt"
    sums = apt_dir / "SHA256SUMS"
    if not sums.exists():
        return []
    expected: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        expected[name.strip()] = digest
    debs: list[Path] = []
    for name, digest in expected.items():
        path = apt_dir / name
        if not path.exists():
            log.warning("bundled package missing: %s", name)
            continue
        if u.sha256_file(path) != digest:
            raise u.IntegrityError(f"bundled package failed checksum: {name}")
        debs.append(path)
    return debs


def install_rofi_user(root: Path, *, offline: bool = False,
                      dry_run: bool = False) -> Path | None:
    """Provide rofi without root by unpacking the Ubuntu .deb set.

    Returns the wrapper path, or None when rofi cannot be provided.
    """
    runtime = Path(root) / "runtime/rofi"
    if shutil.which("rofi"):
        return Path(shutil.which("rofi"))
    if (runtime / "usr/bin/rofi").exists():
        return runtime / "usr/bin/rofi"
    bundled = _bundled_debs(root)
    if dry_run:
        if bundled or shutil.which("apt-get") or shutil.which("rofi"):
            log.info("[dry-run] would unpack rofi and runtime libraries into %s", runtime)
            return runtime / "usr/bin/rofi"
        log.warning("rofi is unavailable both on the system and in the bundle")
        return None
    if not shutil.which("dpkg-deb"):
        log.warning("dpkg-deb unavailable; cannot provide Spotlight")
        return None

    libs = runtime / "usr/lib/x86_64-linux-gnu"
    runtime.mkdir(parents=True, exist_ok=True)
    if bundled:
        log.info("using bundled rofi packages (offline-capable)")
        debs = bundled
    elif offline:
        log.warning("offline mode: rofi is not installed and no bundled packages exist")
        return None
    elif shutil.which("apt-get"):
        with tempfile.TemporaryDirectory(prefix="tahoe-rofi-") as tmp:
            debs = _download_debs(ROFI_DEPS, Path(tmp))
            for deb in debs:
                _extract_deb(deb, runtime)
    else:
        log.warning("no bundled rofi packages and apt-get unavailable")
        return None
    if bundled:
        for deb in debs:
            _extract_deb(deb, runtime)
    if not (runtime / "usr/bin/rofi").exists():
        log.error("rofi binary missing after unpacking packages")
        return None
    # Make our private libraries visible to ldd before judging the binary.
    proc = u.run(["bash", "-lc",
                  f"LD_LIBRARY_PATH={libs} ldd {runtime / 'usr/bin/rofi'}"],
                 check=False, timeout=30)
    missing = [line.strip() for line in (proc.stdout or "").splitlines() if "not found" in line]
    if missing:
        log.error("rofi still has unresolved libraries: %s", "; ".join(missing))
        return None
    log.info("installed rofi %s into the project runtime (no root required)",
             version_of("rofi") or "2.0")
    return runtime / "usr/bin/rofi"


def _extract_deb(deb: Path, runtime: Path) -> None:
    proc = u.run(["dpkg-deb", "-x", str(deb), str(runtime)],
                 timeout=120, check=False)
    if proc.returncode != 0:
        raise u.EngineError(
            f"cannot unpack {deb.name}: {(proc.stderr or proc.stdout or '').strip()}")


def _write_wrapper(root: Path, runtime: Path, wrapper: Path, *, dry_run: bool) -> Path:
    libdir = runtime / "usr/lib/x86_64-linux-gnu"
    binary = runtime / "usr/bin/rofi"
    script = f"""#!/bin/sh
# Generated by macos-tahoe-ubuntu: Spotlight search launcher.
# GNOME/Mutter does not implement wlr-layer-shell, so rofi uses XWayland.
export LD_LIBRARY_PATH="{libdir}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
unset WAYLAND_DISPLAY
export GDK_BACKEND=x11
exec "{binary}" "$@"
"""
    if dry_run:
        log.info("[dry-run] would write Spotlight wrapper %s", wrapper)
        return wrapper
    u.atomic_write_text(wrapper, script, mode=0o755)
    return wrapper
