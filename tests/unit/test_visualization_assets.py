"""Tests for the lazily fetched, integrity-checked dashboard assets."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sagaz.visualization import assets
from sagaz.visualization.assets import (
    MAX_ASSET_BYTES,
    AssetCache,
    AssetUnavailableError,
    PinnedAsset,
    cache_dir,
)
from sagaz.visualization.server import create_app

BODY = b"window.mermaid = {};"
ASSET = PinnedAsset(
    name="mermaid.min.js",
    url="https://cdn.example.test/mermaid.min.js",
    sha384=hashlib.sha384(BODY).hexdigest(),
)


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fake_download(url, timeout):
        calls.append(url)
        return BODY

    monkeypatch.setattr(assets, "_download", fake_download)
    return calls


class TestCacheDir:
    def test_explicit_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAGAZ_CACHE_DIR", str(tmp_path))
        assert cache_dir() == tmp_path

    def test_xdg_cache_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAGAZ_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert cache_dir() == tmp_path / "sagaz"

    def test_home_fallback(self, monkeypatch):
        monkeypatch.delenv("SAGAZ_CACHE_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert cache_dir() == Path.home() / ".cache" / "sagaz"


class TestAssetCache:
    @pytest.mark.asyncio
    async def test_fetches_once_then_serves_from_memory_and_disk(self, tmp_path, downloads):
        cache = AssetCache(tmp_path)
        assert await cache.get(ASSET) == BODY
        assert await cache.get(ASSET) == BODY
        assert downloads == [ASSET.url]
        assert (tmp_path / ASSET.filename).read_bytes() == BODY

        # A fresh process reuses the on-disk copy without downloading.
        assert await AssetCache(tmp_path).get(ASSET) == BODY
        assert downloads == [ASSET.url]

    @pytest.mark.asyncio
    async def test_concurrent_requests_download_once(self, tmp_path, downloads):
        cache = AssetCache(tmp_path)
        results = await asyncio.gather(*(cache.get(ASSET) for _ in range(5)))
        assert results == [BODY] * 5
        assert downloads == [ASSET.url]

    @pytest.mark.asyncio
    async def test_tampered_cache_file_is_replaced(self, tmp_path, downloads):
        (tmp_path / ASSET.filename).write_bytes(b"evil()")
        assert await AssetCache(tmp_path).get(ASSET) == BODY
        assert downloads == [ASSET.url]
        assert (tmp_path / ASSET.filename).read_bytes() == BODY

    @pytest.mark.asyncio
    async def test_integrity_mismatch_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(assets, "_download", lambda url, timeout: b"evil()")
        with pytest.raises(AssetUnavailableError, match="Integrity"):
            await AssetCache(tmp_path).get(ASSET)
        assert not (tmp_path / ASSET.filename).exists()

    @pytest.mark.asyncio
    async def test_network_failure_is_reported(self, tmp_path, monkeypatch):
        def offline(url, timeout):
            message = "offline"
            raise OSError(message)

        monkeypatch.setattr(assets, "_download", offline)
        with pytest.raises(AssetUnavailableError, match="OSError"):
            await AssetCache(tmp_path).get(ASSET)

    @pytest.mark.asyncio
    async def test_unwritable_cache_still_serves(self, tmp_path, downloads, monkeypatch):
        def fail_write(path, data):
            message = "read-only"
            raise PermissionError(message)

        monkeypatch.setattr(assets, "_write_atomic", fail_write)
        assert await AssetCache(tmp_path).get(ASSET) == BODY

    @pytest.mark.asyncio
    async def test_default_directory_uses_cache_dir(self, tmp_path, downloads, monkeypatch):
        monkeypatch.setenv("SAGAZ_CACHE_DIR", str(tmp_path))
        assert await AssetCache().get(ASSET) == BODY
        assert (tmp_path / ASSET.filename).exists()


class TestDownload:
    def test_rejects_non_https(self):
        with pytest.raises(ValueError, match="HTTPS"):
            assets._download("http://cdn.example.test/x.js", 1.0)

    def _fake_urlopen(self, payload):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return payload[:limit]

        return lambda request, timeout: FakeResponse()

    def test_reads_body(self, monkeypatch):
        monkeypatch.setattr(assets, "urlopen", self._fake_urlopen(BODY))
        assert assets._download(ASSET.url, 1.0) == BODY

    def test_rejects_oversized_body(self, monkeypatch):
        monkeypatch.setattr(assets, "urlopen", self._fake_urlopen(b"x" * (MAX_ASSET_BYTES + 5)))
        with pytest.raises(ValueError, match="size limit"):
            assets._download(ASSET.url, 1.0)


def test_write_atomic_cleans_up_on_failure(tmp_path, monkeypatch):
    def broken_replace(self, target):
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(Path, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        assets._write_atomic(tmp_path / "sub" / "file.js", BODY)
    assert list((tmp_path / "sub").iterdir()) == []


class TestMermaidEndpoint:
    def test_serves_cached_asset_with_immutable_caching(self, tmp_path, downloads, monkeypatch):
        monkeypatch.setattr(assets, "MERMAID", ASSET)
        monkeypatch.setattr("sagaz.visualization.server.MERMAID", ASSET)
        with TestClient(create_app(asset_cache=AssetCache(tmp_path))) as client:
            response = client.get("/static/mermaid.min.js")
        assert response.status_code == 200
        assert response.content == BODY
        assert response.headers["content-type"].startswith("text/javascript")
        assert "immutable" in response.headers["cache-control"]

    def test_unavailable_asset_returns_503(self, tmp_path, monkeypatch):
        def offline(url, timeout):
            message = "offline"
            raise OSError(message)

        monkeypatch.setattr(assets, "_download", offline)
        with TestClient(create_app(asset_cache=AssetCache(tmp_path))) as client:
            response = client.get("/static/mermaid.min.js")
        assert response.status_code == 503

    def test_dashboard_references_local_asset_only(self):
        with TestClient(create_app()) as client:
            html = client.get("/").text
        assert 'src="/static/mermaid.min.js"' in html
        assert "cdn.jsdelivr.net" not in html


def test_pinned_mermaid_digest_shape():
    assert len(assets.MERMAID.sha384) == 96
    assert assets.MERMAID.url.startswith("https://")
