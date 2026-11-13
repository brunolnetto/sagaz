"""Tests for sagaz.cli.dlq storage resolution and lifecycle helpers."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import AsyncMock

import click
import pytest

import sagaz.cli.dlq as dlq_mod
from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage
from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

URL_VARS = ("SAGAZ_OUTBOX_URL", "OUTBOX_URL", "SAGAZ_STORAGE_URL", "DATABASE_URL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in URL_VARS:
        monkeypatch.delenv(var, raising=False)


class TestGetStorage:
    @pytest.mark.parametrize("url", [None, "memory://"])
    def test_memory_fallback(self, monkeypatch, url):
        if url:
            monkeypatch.setenv("SAGAZ_OUTBOX_URL", url)
        assert isinstance(dlq_mod._get_storage(), InMemoryOutboxStorage)

    def test_redis(self, monkeypatch):
        monkeypatch.setenv("OUTBOX_URL", "redis://localhost:6379/0")
        assert isinstance(dlq_mod._get_storage(), RedisOutboxStorage)

    @pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
    def test_postgres(self, monkeypatch, scheme):
        monkeypatch.setenv("DATABASE_URL", f"{scheme}://user@localhost/db")
        assert isinstance(dlq_mod._get_storage(), PostgreSQLOutboxStorage)

    @pytest.mark.parametrize(
        ("url", "path"),
        [("sqlite:///tmp/outbox.db", "/tmp/outbox.db"), ("sqlite://", ":memory:")],  # noqa: S108
    )
    def test_sqlite(self, monkeypatch, url, path):
        monkeypatch.setenv("SAGAZ_STORAGE_URL", url)
        storage = dlq_mod._get_storage()
        assert isinstance(storage, SQLiteOutboxStorage)
        assert storage.db_path == path

    def test_unsupported_scheme(self, monkeypatch):
        monkeypatch.setenv("SAGAZ_OUTBOX_URL", "mongodb://localhost")
        with pytest.raises(click.ClickException, match="Unsupported outbox URL"):
            dlq_mod._get_storage()

    def test_env_precedence(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user@localhost/db")
        monkeypatch.setenv("SAGAZ_OUTBOX_URL", "redis://localhost")
        assert isinstance(dlq_mod._get_storage(), RedisOutboxStorage)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_and_close_are_awaited_when_present(self):
        storage = AsyncMock()
        await dlq_mod._initialize_storage(storage)
        await dlq_mod._close_storage(storage)
        storage.initialize.assert_awaited_once()
        storage.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_hooks_are_skipped(self):
        storage = object()
        await dlq_mod._initialize_storage(storage)
        await dlq_mod._close_storage(storage)


def test_module_without_rich_falls_back_to_none():
    rich_keys = [k for k in sys.modules if k == "rich" or k.startswith("rich.")]
    orig_rich = {k: sys.modules.pop(k) for k in rich_keys}
    sys.modules["rich"] = None  # type: ignore[assignment]
    try:
        reloaded = importlib.reload(dlq_mod)
        assert reloaded.console is None
        assert reloaded.Table is None
    finally:
        del sys.modules["rich"]
        sys.modules.update(orig_rich)
        importlib.reload(dlq_mod)
