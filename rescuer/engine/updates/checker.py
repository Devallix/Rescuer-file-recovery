import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Callable

import requests

from rescuer.core.database import Database

log = logging.getLogger("rescuer.engine.updates")


@dataclass
class UpdateInfo:
    version: str
    url: str
    notes: str
    published_at: str
    size_bytes: int = 0
    sha256: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.version and self.url)


class UpdateError(Exception):
    pass


def version_key(value: str) -> tuple[int, ...]:
    """Turn a version string into a comparable tuple.

    Handles an optional ``v`` prefix and pre-release/build suffixes, so
    ``v0.1.10`` correctly sorts above ``0.1.9`` (plain string comparison
    would get this backwards).
    """
    text = str(value or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    core = text.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for part in core.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(latest: str, current: str) -> bool:
    """Return True when ``latest`` is a strictly newer version than ``current``."""
    return version_key(latest) > version_key(current)


def check_for_updates(
    current_version: str,
    endpoint: str,
    timeout: int = 15,
) -> UpdateInfo | None:
    try:
        resp = requests.get(
            endpoint,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": f"Rescuer/{current_version}",
            },
        )
        resp.raise_for_status()
    except Exception as exc:
        raise UpdateError(f"Update check failed: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateError("Invalid update manifest: not JSON") from exc

    if not isinstance(data, dict):
        raise UpdateError("Invalid update manifest: not a JSON object")

    latest_version = str(data.get("version", "") or "").strip()
    if latest_version[:1] in ("v", "V"):
        latest_version = latest_version[1:]
    if not latest_version:
        raise UpdateError("Invalid update manifest: missing version")

    # Never offer an older build (e.g. after a manual install or rollback).
    if not is_newer(latest_version, current_version):
        return None

    url = str(data.get("url", "") or "").strip()
    if not url:
        raise UpdateError("Invalid update manifest: missing download URL")

    try:
        size_bytes = int(data.get("size_bytes", 0) or 0)
    except (TypeError, ValueError):
        size_bytes = 0

    return UpdateInfo(
        version=latest_version,
        url=url,
        notes=str(data.get("notes", "") or ""),
        published_at=str(data.get("published_at", "") or ""),
        size_bytes=size_bytes,
        sha256=str(data.get("sha256", "") or ""),
    )


def download_update(url: str, dest: str | None = None, timeout: int = 60, progress: Callable[[int, int], None] | None = None) -> str:
    if dest is None:
        suffix = os.path.splitext(url)[1] or ".tmp"
        fd, dest = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            written = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
                        if progress is not None and total > 0:
                            progress(written, total)
    except Exception as exc:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise UpdateError(f"Download failed: {exc}") from exc
    return dest


def verify_sha256(path: str, expected: str) -> bool:
    if not expected:
        return True
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def record_check(db: Database, version: str, status: str, detail: str = "") -> None:
    db.execute(
        "INSERT INTO events (level, source, message) VALUES (?, ?, ?)",
        ("info", "updates", f"update_check {version} {status}: {detail}"),
    )
