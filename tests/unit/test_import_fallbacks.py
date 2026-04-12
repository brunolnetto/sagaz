"""Tests for ImportError fallback paths in all optional-dependency modules.

Uses the sys.modules trick: setting sys.modules[key] = None makes `import key`
raise ImportError, allowing us to test the except ImportError branches.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch


def _reload_module(mod_key: str, blocked_imports: dict) -> object:
    """Remove module from cache, block given imports, reimport and return fresh module."""
    saved_mod = sys.modules.pop(mod_key, None)
    try:
        with patch.dict(sys.modules, blocked_imports):
            return importlib.import_module(mod_key)
    finally:
        # Always restore the *original* (working) module so other tests continue to work
        if saved_mod is not None:
            sys.modules[mod_key] = saved_mod
        elif mod_key in sys.modules:
            del sys.modules[mod_key]


class TestRedisSnapshotFallback:
    def test_redis_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.redis.snapshot",
            {"redis": None, "redis.asyncio": None},
        )
        assert mod.REDIS_AVAILABLE is False
        assert mod.redis is None

    def test_zstd_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.redis.snapshot",
            {"zstandard": None},
        )
        assert mod.ZSTD_AVAILABLE is False
        assert mod.zstd is None


class TestRedisSagaFallback:
    def test_redis_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.redis.saga",
            {"redis": None, "redis.asyncio": None},
        )
        assert mod.REDIS_AVAILABLE is False
        assert mod.redis is None


class TestPostgreSQLSagaFallback:
    def test_asyncpg_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.postgresql.saga",
            {"asyncpg": None},
        )
        assert mod.ASYNCPG_AVAILABLE is False
        assert mod.asyncpg is None


class TestPostgreSQLSnapshotFallback:
    def test_asyncpg_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.postgresql.snapshot",
            {"asyncpg": None},
        )
        assert mod.ASYNCPG_AVAILABLE is False
        assert mod.asyncpg is None


class TestPostgreSQLOutboxFallback:
    def test_asyncpg_unavailable_sets_none(self):
        mod = _reload_module(
            "sagaz.storage.backends.postgresql.outbox",
            {"asyncpg": None},
        )
        assert mod.asyncpg is None


class TestS3SnapshotFallback:
    def test_aioboto3_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.s3.snapshot",
            {"aioboto3": None},
        )
        assert mod.AIOBOTO3_AVAILABLE is False
        assert mod.aioboto3 is None

    def test_zstd_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.storage.backends.s3.snapshot",
            {"zstandard": None},
        )
        assert mod.ZSTD_AVAILABLE is False
        assert mod.zstd is None


class TestKafkaFallback:
    def test_kafka_unavailable_sets_flag(self):
        mod = _reload_module(
            "sagaz.outbox.brokers.kafka",
            {"aiokafka": None},
        )
        assert mod.KAFKA_AVAILABLE is False
        assert mod.AIOKafkaProducer is None
        assert mod.KafkaError is Exception


class TestBrokerFactoryFallback:
    def test_check_broker_availability_returns_false_on_import_error(self):
        """_check_broker_availability returns False when module import fails."""
        from sagaz.core.outbox.brokers.factory import _check_broker_availability

        # Use a nonexistent module path to trigger ImportError
        result = _check_broker_availability("sagaz.__nonexistent_module__", "AVAILABLE")
        assert result is False

    def test_create_broker_raises_on_import_error_with_dependency(self):
        """create_broker raises MissingDependencyError when dependency import fails."""
        import pytest

        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.core.outbox.brokers.factory import _BROKER_REGISTRY

        # Patch a broker factory to raise ImportError, with a dependency set
        original = _BROKER_REGISTRY.get("kafka")
        if original is None:
            return  # skip if kafka not registered

        def _raise_import(_kwargs):
            msg = "no module"
            raise ImportError(msg)

        try:
            _BROKER_REGISTRY["kafka"] = (_raise_import, "aiokafka")
            from sagaz.core.outbox.brokers.factory import create_broker

            with pytest.raises(MissingDependencyError):
                create_broker("kafka")
        finally:
            _BROKER_REGISTRY["kafka"] = original


class TestStorageManagerRedisFallback:
    async def test_initialize_redis_raises_missing_dependency(self):
        """StorageManager raises MissingDependencyError when redis is unavailable."""
        import pytest

        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.core.storage.manager import StorageManager

        manager = StorageManager(
            backend="redis",
            saga_url="redis://localhost:6379/0",
        )

        with patch.dict(sys.modules, {"redis": None, "redis.asyncio": None}):
            with pytest.raises((MissingDependencyError, ImportError)):
                await manager._initialize_redis_unified()
