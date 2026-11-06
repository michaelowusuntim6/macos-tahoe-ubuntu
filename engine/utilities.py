"""Small, well-tested helpers shared by the automation engine."""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

log = logging.getLogger("engine")


class EngineError(RuntimeError):
    """Base class for expected, user-facing engine failures."""


class CommandError(EngineError):
    def __init__(self, argv: Sequence[str], returncode: int | None,
                 stdout: str = "", stderr: str = "", reason: str = ""):
        self.argv = list(argv)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.reason = reason
        cmd = " ".join(argv)
        detail = (stderr or stdout or reason).strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "…"
        super().__init__(f"command failed ({returncode}): {cmd}\n{detail}")


class ConfigError(EngineError):
    pass


class IntegrityError(EngineError):
    pass


# ───────────────────────────── process helpers ─────────────────────────────

def run(argv: Sequence[str], *, timeout: float = 120, check: bool = True,
        capture: bool = True, env: dict[str, str] | None = None,
        cwd: Path | str | None = None,
        input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    argv = [str(a) for a in argv]
    log.debug("exec: %s", " ".join(argv))
    try:
        proc = subprocess.run(
            argv, timeout=timeout, text=True,
            capture_output=capture, env=env, cwd=cwd, input=input_text,
        )
    except FileNotFoundError as exc:
        raise CommandError(argv, None, reason=f"executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(argv, None, reason=f"timed out after {timeout}s") from exc
    if check and proc.returncode != 0:
        raise CommandError(argv, proc.returncode, proc.stdout or "", proc.stderr or "")
    return proc


def which(name: str) -> str | None:
    return shutil.which(name)


def require_commands(names: Iterable[str]) -> None:
    missing = [n for n in names if not which(n)]
    if missing:
        raise EngineError(
            "missing required command(s): " + ", ".join(missing)
            + ". Install them with: sudo apt install " + " ".join(missing)
        )


# ───────────────────────────── filesystem helpers ──────────────────────────

def data_home() -> Path:
    """XDG data directory, matching what GNOME/GTK read."""
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode)


def atomic_write_json(path: Path, obj: Any, mode: int = 0o644) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=False) + "\n", mode)


def read_json(path: Path, *, required: bool = True) -> Any:
    path = Path(path)
    if not path.exists():
        if required:
            raise ConfigError(f"missing JSON file: {path}")
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"malformed JSON in {path}: line {exc.lineno}: {exc.msg}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    """Hash relative names, permissions and contents in a stable order."""
    root = Path(path)
    digest = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        rel = item.relative_to(root).as_posix()
        if item.is_symlink():
            digest.update(f"L {rel} {os.readlink(item)}\n".encode())
        elif item.is_dir():
            digest.update(f"D {rel}\n".encode())
        else:
            digest.update(f"F {rel} {item.stat().st_mode & 0o777}\n".encode())
            with item.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def copy_tree_atomic(src: Path, dest: Path) -> None:
    """Replace dest with a copy of src without leaving a half-written tree."""
    src, dest = Path(src), Path(dest)
    if not src.exists():
        raise EngineError(f"source tree missing: {src}")
    ensure_dir(dest.parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    try:
        for child in src.iterdir():
            target = staging / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, target, symlinks=True)
            else:
                shutil.copy2(child, target, follow_symlinks=False)
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        os.replace(staging, dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def remove_path(path: Path) -> None:
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def safe_extract_tar(archive: Path, dest: Path) -> None:
    """Extract a tarball, refusing path traversal and escaping links."""
    dest = ensure_dir(Path(dest))
    with tarfile.open(archive, "r:*") as tf:
        try:
            tf.extractall(dest, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise IntegrityError(f"cannot extract {archive}: {exc}") from exc


def safe_extract_zip(archive: Path, dest: Path) -> None:
    dest = ensure_dir(Path(dest))
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep):
                raise IntegrityError(f"zip entry escapes destination: {member.filename}")
        zf.extractall(dest)


def find_files(root: Path, pattern: str) -> list[Path]:
    return sorted(Path(root).rglob(pattern))


# ───────────────────────────── gsettings helpers ───────────────────────────

def _schema_dir_for(schema: str, extra_dirs: Iterable[Path] = ()) -> Path | None:
    candidates = list(extra_dirs)
    ext_root = data_home() / "gnome-shell/extensions"
    if ext_root.is_dir():
        for ext in ext_root.iterdir():
            candidates.append(ext / "schemas")
    for directory in candidates:
        if (directory / f"{schema}.gschema.xml").exists():
            return directory
        # Some extensions ship one XML file with many schema ids.
        if directory.is_dir() and any(directory.glob("*.gschema.xml")):
            probe = run(["gsettings", "--schemadir", str(directory),
                         "list-keys", schema], check=False, timeout=15)
            if probe.returncode == 0:
                return directory
    return None


def gsettings_schema_exists(schema: str, schemadir: Path | None = None) -> bool:
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["list-keys", schema]
    proc = run(argv, check=False, timeout=20)
    return proc.returncode == 0


def gsettings_get(schema: str, key: str, schemadir: Path | None = None) -> str | None:
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["get", schema, key]
    proc = run(argv, check=False, timeout=20)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def to_gvariant(value: Any) -> str:
    """Serialise a Python value as gsettings/GVariant text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(to_gvariant(v) for v in value) + "]"
    raise ConfigError(f"cannot convert {value!r} to a gsettings value")


def gsettings_set(schema: str, key: str, value: Any,
                  schemadir: Path | None = None) -> None:
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["set", schema, key, to_gvariant(value)]
    run(argv, timeout=30)


def gsettings_set_raw(schema: str, key: str, raw: str,
                      schemadir: Path | None = None) -> None:
    """Set a key from GVariant text captured by gsettings_get()."""
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["set", schema, key, raw]
    run(argv, timeout=30)


def gsettings_reset(schema: str, key: str, schemadir: Path | None = None) -> None:
    argv = ["gsettings"]
    if schemadir:
        argv += ["--schemadir", str(schemadir)]
    argv += ["reset", schema, key]
    run(argv, timeout=30, check=False)


def gsettings_array(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def settings_schemadir(schema: str) -> Path | None:
    return _schema_dir_for(schema)


def dconf_available() -> bool:
    return bool(which("dconf"))


# ───────────────────────────── misc ────────────────────────────────────────

def parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            data[key] = val.strip().strip('"').strip("'")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    return data


def gnome_shell_version() -> str | None:
    if not which("gnome-shell"):
        return None
    proc = run(["gnome-shell", "--version"], check=False, timeout=20)
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr).strip()
    for token in text.split():
        if token and token[0].isdigit():
            return token
    return None


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE") or "unknown"


def human_mb(kib: int) -> str:
    return f"{kib / 1024:.0f} MiB"
