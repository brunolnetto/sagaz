"""
Tests for missing paths in sagaz/storage/manager.py.

Missing lines: 241-242, 250-252, 290-291, 349-350, 352-353, 355-356,
              369, 371-372, 374, 378, 380-383, 388, 392, 395, 403-404,
              408, 410-413, 467, 477
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestUnifiedPostgreSQLMissingDependency:
    """Lines 241-242: PostgreSQL init raises MissingDependencyError when asyncpg not installed."""

    @pytest.mark.asyncio
    async def test_postgresql_without_asyncpg_raises(self):
        """Lines 241-242: MissingDependencyError when asyncpg not available."""
        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.storage.manager import StorageManager

        with patch.dict(sys.modules, {"asyncpg": None}):
            manager = StorageManager(url="postgresql://user:pass@localhost/db")
            with pytest.raises(MissingDependencyError, match="asyncpg"):
                await manager.initialize()


class TestUnifiedRedisMissingDependency:
    """Lines 290-291: Redis init raises MissingDependencyError when redis not installed."""

    @pytest.mark.asyncio
    async def test_redis_without_redis_package_raises(self):
        """Lines 290-291: MissingDependencyError when redis not available."""
        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.storage.manager import StorageManager

        with patch.dict(sys.modules, {"redis": None, "redis.asyncio": None}):
            manager = StorageManager(url="redis://localhost:6379")
            with pytest.raises(MissingDependencyError, match="redis"):
                await manager.initialize()


class TestCreateSagaStoragePaths:
    """Lines 349-356: _create_saga_storage different backend types."""

    def test_create_postgresql_saga_storage(self):
        """Lines 349-350: _create_postgresql_saga returns PostgreSQLSagaStorage object."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = manager._create_postgresql_saga("postgresql://localhost/db")
        assert result is not None
        assert result.__class__.__name__ == "PostgreSQLSagaStorage"

    def test_create_redis_saga_storage(self):
        """Lines 352-353: _create_redis_saga returns RedisSagaStorage object."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = manager._create_redis_saga("redis://localhost:6379")
        assert result is not None
        assert result.__class__.__name__ == "RedisSagaStorage"

    @pytest.mark.asyncio
    async def test_create_saga_storage_unknown_raises(self):
        """Lines 355-356: Unknown saga backend raises ValueError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with pytest.raises(ValueError, match="Unknown saga backend"):
            await manager._create_saga_storage("foobar", "foobar://localhost")

    @pytest.mark.asyncio
    async def test_create_outbox_storage_unknown_raises(self):
        """Lines 380-383: Unknown outbox backend raises ValueError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with pytest.raises(ValueError, match="Unknown outbox backend"):
            await manager._create_outbox_storage("foobar", "foobar://localhost")

    @pytest.mark.asyncio
    async def test_hybrid_memory_sqlite(self):
        """Lines 349, 369: hybrid mode uses _create_saga_storage for memory path."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(
            saga_url="memory://",
            outbox_url="sqlite://:memory:",
        )
        assert manager.is_hybrid
        await manager.initialize()
        assert manager.saga.__class__.__name__ == "InMemorySagaStorage"
        assert manager.outbox.__class__.__name__ == "SQLiteOutboxStorage"
        await manager.close()


class TestCreateOutboxStoragePaths:
    """Lines 388-413: _create_outbox_storage different backend types."""

    @pytest.mark.asyncio
    async def test_create_postgresql_outbox(self):
        """Lines 388, 392: _create_postgresql_outbox with mocked initialize."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with patch(
            "sagaz.storage.backends.postgresql.outbox.PostgreSQLOutboxStorage.initialize",
            new_callable=AsyncMock,
        ):
            result = await manager._create_postgresql_outbox("postgresql://localhost/db")
            assert result is not None

    @pytest.mark.asyncio
    async def test_create_redis_outbox(self):
        """Lines 403-404: _create_redis_outbox with mocked initialize."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with patch(
            "sagaz.storage.backends.redis.outbox.RedisOutboxStorage.initialize",
            new_callable=AsyncMock,
        ):
            result = await manager._create_redis_outbox("redis://localhost:6379")
            assert result is not None

    @pytest.mark.asyncio
    async def test_create_memory_outbox(self):
        """Line 388: memory outbox created."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        outbox = await manager._create_outbox_storage("memory", None)
        assert outbox is not None

    @pytest.mark.asyncio
    async def test_create_sqlite_outbox(self):
        """Lines 408-413: SQLite outbox created."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        outbox = await manager._create_outbox_storage("sqlite", "sqlite://:memory:")
        assert outbox is not None


class TestStorageManagerClose:
    """Lines 467: close() with shared pool (asyncpg-style)."""

    @pytest.mark.asyncio
    async def test_close_with_asyncpg_shared_pool(self):
        """Line 467: close() calls pool.close() + wait_closed() for asyncpg pool."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()

        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()  # async (current asyncpg style)
        mock_pool.wait_closed = AsyncMock()  # async

        manager._shared_pool = mock_pool
        manager._saga_storage = None
        manager._outbox_storage = None

        await manager.close()

        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_called_once()
        assert manager._shared_pool is None

    @pytest.mark.asyncio
    async def test_close_with_redis_shared_pool(self):
        """Line 467: close() calls await pool.close() for Redis connection."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()

        mock_pool = AsyncMock()
        # Redis pool doesn't have wait_closed
        del mock_pool.wait_closed

        manager._shared_pool = mock_pool
        manager._saga_storage = None
        manager._outbox_storage = None

        await manager.close()

        mock_pool.close.assert_called_once()
        assert manager._shared_pool is None


class TestStorageManagerHealthCheck:
    """Line 477: health_check with unhealthy storages."""

    @pytest.mark.asyncio
    async def test_health_check_saga_raises_exception(self):
        """Line 477: Exception in saga health check captured in result."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        await manager.initialize()  # memory backend

        # Replace saga storage with one that throws on health_check
        mock_saga = AsyncMock()
        mock_saga.health_check = AsyncMock(side_effect=Exception("DB unavailable"))
        manager._saga_storage = mock_saga  # type: ignore[assignment]

        result = await manager.health_check()

        assert result["saga"]["status"] == "unhealthy"
        assert "DB unavailable" in result["saga"]["error"]
        assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_outbox_raises_exception(self):
        """Line 477: Exception in outbox health check captured."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        await manager.initialize()  # memory backend

        mock_outbox = AsyncMock()
        mock_outbox.health_check = AsyncMock(side_effect=RuntimeError("timeout"))
        manager._outbox_storage = mock_outbox  # type: ignore[assignment]

        result = await manager.health_check()

        assert result["outbox"]["status"] == "unhealthy"
        assert result["status"] == "unhealthy"


class TestManagerAdditionalMissingPaths:
    """Lines 241-242, 317->321, 347, 350, 353, 378-383, 395, 398, 437->445, 467, 477."""

    @pytest.mark.asyncio
    async def test_initialize_unified_unknown_backend_raises(self):
        """Lines 241-242: ValueError for unknown backend type in _initialize_unified."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with pytest.raises(ValueError, match="Unknown backend type"):
            await manager._initialize_unified("foobar")

    @pytest.mark.asyncio
    async def test_initialize_sqlite_unified_without_scheme(self):
        """Lines 317->321: db_path without sqlite:// scheme passes as-is."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(
            saga_url=":memory:",
            outbox_url=":memory:",
        )
        manager._saga_url = ":memory:"  # no sqlite:// prefix
        await manager._initialize_sqlite_unified()
        assert manager._saga_storage is not None
        await manager.close()

    @pytest.mark.asyncio
    async def test_create_saga_storage_postgresql(self):
        """Line 347: _create_saga_storage dispatches to postgresql."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = await manager._create_saga_storage("postgresql", "postgresql://localhost/db")
        assert result.__class__.__name__ == "PostgreSQLSagaStorage"

    @pytest.mark.asyncio
    async def test_create_saga_storage_redis(self):
        """Line 350: _create_saga_storage dispatches to redis."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = await manager._create_saga_storage("redis", "redis://localhost:6379")
        assert result.__class__.__name__ == "RedisSagaStorage"

    @pytest.mark.asyncio
    async def test_create_saga_storage_sqlite(self):
        """Lines 353, 378-383: _create_saga_storage dispatches to sqlite."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = await manager._create_saga_storage("sqlite", "sqlite://:memory:")
        assert result.__class__.__name__ == "SQLiteSagaStorage"

    @pytest.mark.asyncio
    async def test_create_outbox_storage_postgresql(self):
        """Line 395: _create_outbox_storage dispatches to postgresql."""
        from unittest.mock import AsyncMock, patch

        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        with patch(
            "sagaz.storage.backends.postgresql.outbox.PostgreSQLOutboxStorage.initialize",
            new_callable=lambda: lambda self: AsyncMock()(),
        ) as _:
            result = await manager._create_outbox_storage("postgresql", "postgresql://localhost/db")
        assert result.__class__.__name__ == "PostgreSQLOutboxStorage"

    @pytest.mark.asyncio
    async def test_create_outbox_storage_redis(self):
        """Line 398: _create_outbox_storage dispatches to redis."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        result = await manager._create_outbox_storage("redis", "redis://localhost:6379")
        assert result.__class__.__name__ == "RedisOutboxStorage"

    @pytest.mark.asyncio
    async def test_close_pool_without_close_method(self):
        """Lines 437->445: close() skips close() call when pool has no close attr."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()

        class NoClosePool:
            pass

        manager._shared_pool = NoClosePool()  # type: ignore[assignment]
        manager._saga_storage = None
        manager._outbox_storage = None

        await manager.close()
        assert manager._shared_pool is None

    @pytest.mark.asyncio
    async def test_health_check_saga_without_health_check_method(self):
        """Line 467: saga storage without health_check method returns healthy."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        mock_saga = MagicMock()  # No health_check attribute
        del mock_saga.health_check
        manager._saga_storage = mock_saga  # type: ignore[assignment]
        manager._outbox_storage = None

        result = await manager.health_check()
        assert result["saga"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_outbox_without_health_check_method(self):
        """Line 477: outbox storage without health_check method returns healthy."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager()
        manager._saga_storage = None
        mock_outbox = MagicMock()
        del mock_outbox.health_check
        manager._outbox_storage = mock_outbox  # type: ignore[assignment]

        result = await manager.health_check()
        assert result["outbox"]["status"] == "healthy"
