"""Lazily fetched, integrity-checked front-end assets for the dashboard.

Mermaid (~2.5 MB) is not shipped in the wheel. On first request the monitor
downloads the pinned build once, verifies its SHA-384 digest, caches it on
disk and serves it from the monitor itself. Browsers therefore never contact a
CDN, and the core package stays small. Operators in air-gapped environments can
pre-populate the cache directory (see :func:`cache_dir`).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

MAX_ASSET_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PinnedAsset:
    name: str
    url: str
    sha384: str  # hex digest

    @property
    def filename(self) -> str:
        return f"{self.sha384[:16]}-{self.name}"


MERMAID = PinnedAsset(
    name="mermaid.min.js",
    url="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js",
    sha384=(
        "adbb6301d9c8404fda409184817ad55253226dd7d349ae0f"
        "423bb81c384ddec4763e668a17384469fb9e3ec97d1fff48"
    ),
)


class AssetUnavailableError(RuntimeError):
    """The asset is not cached and could not be fetched and verified."""


def cache_dir() -> Path:
    """``$SAGAZ_CACHE_DIR``, else ``$XDG_CACHE_HOME/sagaz``, else ``~/.cache/sagaz``."""
    override = os.environ.get("SAGAZ_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "sagaz"


def _digest(data: bytes) -> str:
    return hashlib.sha384(data).hexdigest()


def _download(url: str, timeout: float) -> bytes:
    if not url.startswith("https://"):
        message = "Asset URLs must use HTTPS"
        raise ValueError(message)
    request = Request(url, headers={"User-Agent": "sagaz-monitor"})
    # Scheme is restricted to https above.
    with urlopen(request, timeout=timeout) as response:  # nosec B310
        data = response.read(MAX_ASSET_BYTES + 1)
    if len(data) > MAX_ASSET_BYTES:
        message = "Asset exceeds size limit"
        raise ValueError(message)
    return bytes(data)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class AssetCache:
    """Process-wide accessor that fetches each pinned asset at most once."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.directory = directory
        self.timeout_seconds = timeout_seconds
        self._memory: dict[str, bytes] = {}
        self._lock = asyncio.Lock()

    def _path(self, asset: PinnedAsset) -> Path:
        return (self.directory or cache_dir()) / asset.filename

    def _read_cached(self, asset: PinnedAsset) -> bytes | None:
        path = self._path(asset)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if _digest(data) != asset.sha384:
            path.unlink(missing_ok=True)  # corrupted or tampered: refetch
            return None
        return data

    def _fetch(self, asset: PinnedAsset) -> bytes:
        cached = self._read_cached(asset)
        if cached is not None:
            return cached
        try:
            data = _download(asset.url, self.timeout_seconds)
        except (OSError, ValueError) as exc:
            message = f"Could not fetch {asset.name}: {type(exc).__name__}"
            raise AssetUnavailableError(message) from exc
        if _digest(data) != asset.sha384:
            message = f"Integrity check failed for {asset.name}"
            raise AssetUnavailableError(message)
        try:
            _write_atomic(self._path(asset), data)
        except OSError:
            pass  # read-only cache dir: still serve from memory
        return data

    async def get(self, asset: PinnedAsset) -> bytes:
        data = self._memory.get(asset.sha384)
        if data is not None:
            return data
        async with self._lock:
            data = self._memory.get(asset.sha384)
            if data is None:
                data = await asyncio.to_thread(self._fetch, asset)
                self._memory[asset.sha384] = data
            return data
