"""HTTPS downloads with retries, timeouts and checksum verification."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import utilities as u

log = logging.getLogger("engine")

USER_AGENT = "macos-tahoe-ubuntu/1.0 (+desktop customization installer)"


class OfflineUnavailable(u.EngineError):
    pass


class Downloader:
    def __init__(self, cache_dir: Path, *, offline: bool = False,
                 retries: int = 3, timeout: float = 60):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.retries = retries
        self.timeout = timeout

    def _cached_ok(self, cache_path: Path, sha256: str | None) -> bool:
        if not cache_path.exists():
            return False
        if cache_path.stat().st_size == 0:
            return False
        if sha256 and u.sha256_file(cache_path) != sha256:
            log.warning("cached file failed checksum, discarding: %s", cache_path)
            cache_path.unlink(missing_ok=True)
            return False
        return True

    def fetch(self, url: str, *, filename: str, sha256: str | None = None,
              required: bool = True) -> Path | None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise u.EngineError(f"refusing non-HTTPS download: {url}")
        dest = self.cache_dir / filename
        if self._cached_ok(dest, sha256):
            log.debug("using cached %s", dest)
            return dest
        if self.offline:
            if required:
                raise OfflineUnavailable(
                    f"offline mode: {filename} is not cached and cannot be downloaded ({url})")
            return None

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            tmp = dest.with_name(f".{dest.name}.part-{attempt}")
            try:
                log.info("downloading %s (attempt %d/%d)", filename, attempt, self.retries)
                digest = self._download(url, tmp)
                if sha256 and digest != sha256:
                    raise u.IntegrityError(
                        f"checksum mismatch for {filename}: expected {sha256}, got {digest}")
                if tmp.stat().st_size == 0:
                    raise u.IntegrityError(f"downloaded file is empty: {filename}")
                tmp.replace(dest)
                u.atomic_write_json(self.cache_dir / f"{filename}.meta.json",
                                    {"url": url, "sha256": digest,
                                     "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                return dest
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    OSError, u.IntegrityError) as exc:
                last_error = exc
                tmp.unlink(missing_ok=True)
                log.warning("download failed (%s): %s", filename, exc)
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
        if required:
            raise u.EngineError(f"could not download {filename} from {url}: {last_error}")
        log.error("optional download failed: %s (%s)", filename, last_error)
        return None

    def _download(self, url: str, tmp: Path) -> str:
        import hashlib
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise u.EngineError(f"HTTP {status} for {url}")
            expected = response.headers.get("Content-Length")
            written = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                fh.flush()
                import os
                os.fsync(fh.fileno())
            if expected is not None and int(expected) != written:
                raise u.IntegrityError(
                    f"incomplete download: expected {expected} bytes, got {written}")
        return digest.hexdigest()

    def fetch_json(self, url: str, *, timeout: float | None = None) -> dict:
        if self.offline:
            raise OfflineUnavailable(f"offline mode: cannot query {url}")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise u.EngineError(f"refusing non-HTTPS request: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(attempt)
        raise u.EngineError(f"cannot fetch JSON {url}: {last}")
