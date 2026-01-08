"""
Tests for StorageManager facade pattern.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBaseStorageManager:
    """Tests for the abstract BaseStorageManager base class."""

    def test_base_storage_manager_is_abstract(self):
        """Test that BaseStorageManager cannot be instantiated directly."""
        from sagaz.storage.manager import BaseStorageManager

        with pytest.raises(TypeError):
            BaseStorageManager()


class TestInMemoryStorageManager:
    """Tests for in-memory StorageManager configuration."""

    @pytest.mark.asyncio
    async def test_initialize_creates_storages(self):
        """Test that initialize creates both saga and outbox storage."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        await manager.initialize()

        try:
            assert manager.saga is not None
            assert manager.outbox is not None
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_saga_property_before_init_raises(self):
        """Test accessing saga before init raises RuntimeError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.saga

    @pytest.mark.asyncio
    async def test_outbox_property_before_init_raises(self):
        """Test accessing outbox before init raises RuntimeError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.outbox

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager support."""
        from sagaz.storage.manager import StorageManager

        async with StorageManager(url="memory://") as manager:
            assert manager.saga is not None
            assert manager.outbox is not None

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check returns healthy status."""
        from sagaz.storage.manager import StorageManager

        async with StorageManager(url="memory://") as manager:
            health = await manager.health_check()

            assert health["status"] == "healthy"
            assert health["saga_backend"] == "memory"
            assert health["outbox_backend"] == "memory"
            assert health["mode"] == "unified"

    @pytest.mark.asyncio
    async def test_saga_operations(self):
        """Test saga storage operations through manager."""
        from sagaz.storage.manager import StorageManager
        from sagaz.types import SagaStatus

        async with StorageManager(url="memory://") as manager:
            await manager.saga.save_saga_state(
                saga_id="test-saga-1",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"key": "value"},
            )

            loaded = await manager.saga.load_saga_state("test-saga-1")

            assert loaded is not None
            assert loaded["saga_name"] == "TestSaga"

    @pytest.mark.asyncio
    async def test_outbox_operations(self):
        """Test outbox storage operations through manager."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.manager import StorageManager

        async with StorageManager(url="memory://") as manager:
            event = OutboxEvent(
                saga_id="test-saga-1",
                event_type="TestEvent",
                payload={"data": "test"},
            )

            await manager.outbox.insert(event)

            loaded = await manager.outbox.get_by_id(event.event_id)

            assert loaded is not None
            assert loaded.saga_id == "test-saga-1"


class TestCreateStorageManager:
    """Tests for create_storage_manager factory function."""

    def test_create_memory_from_url(self):
        """Test creating memory manager from URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("memory://")
        assert isinstance(manager, StorageManager)

    def test_create_memory_from_none(self):
        """Test creating memory manager from None URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager(None)
        assert isinstance(manager, StorageManager)

    def test_create_memory_from_backend(self):
        """Test creating memory manager from explicit backend."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager(backend="memory")
        assert isinstance(manager, StorageManager)

    def test_create_postgresql_from_url(self):
        """Test creating PostgreSQL manager from URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("postgresql://localhost/db")
        assert isinstance(manager, StorageManager)

    def test_create_postgresql_from_postgres_url(self):
        """Test creating PostgreSQL manager from postgres:// URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("postgres://localhost/db")
        assert isinstance(manager, StorageManager)

    def test_create_redis_from_url(self):
        """Test creating Redis manager from URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("redis://localhost:6379")
        assert isinstance(manager, StorageManager)

    def test_create_sqlite_from_url(self):
        """Test creating SQLite manager from URL."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("sqlite:///tmp/test.db")
        assert isinstance(manager, StorageManager)

    def test_create_sqlite_from_file_path(self):
        """Test creating SQLite manager from file path."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager("/tmp/test.db")
        assert isinstance(manager, StorageManager)

    def test_create_sqlite_memory(self):
        """Test creating SQLite :memory: manager."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager(":memory:")
        assert isinstance(manager, StorageManager)

    def test_create_from_explicit_backend(self):
        """Test creating manager from explicit backend."""
        from sagaz.storage.manager import StorageManager, create_storage_manager

        manager = create_storage_manager(
            url="postgresql://localhost/db",
            backend="postgresql",
            pool_min_size=10,
        )
        assert isinstance(manager, StorageManager)

    def test_create_unknown_backend_raises(self):
        """Test creating manager with unknown backend raises ValueError."""
        from sagaz.storage.manager import create_storage_manager

        with pytest.raises(ValueError, match="Unknown backend"):
            create_storage_manager(backend="unknown")

    def test_create_postgresql_without_url_raises(self):
        """Test creating PostgreSQL without URL raises ValueError."""
        from sagaz.storage.manager import create_storage_manager

        with pytest.raises(ValueError, match="url is required"):
            create_storage_manager(backend="postgresql")

    def test_create_unknown_url_raises(self):
        """Test creating manager with unknown URL scheme raises ValueError."""
        from sagaz.storage.manager import create_storage_manager

        with pytest.raises(ValueError, match="Cannot determine backend"):
            create_storage_manager("unknown://localhost")


class TestPostgreSQLStorageManager:
    """Tests for PostgreSQL StorageManager configuration."""

    def test_saga_property_before_init_raises(self):
        """Test accessing saga before init raises RuntimeError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="postgresql://localhost/db")

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.saga

    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self):
        """Test health check when not initialized."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="postgresql://localhost/db")
        health = await manager.health_check()

        assert health["status"] == "unhealthy"


class TestRedisStorageManager:
    """Tests for Redis StorageManager configuration."""

    def test_saga_property_before_init_raises(self):
        """Test accessing saga before init raises RuntimeError."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="redis://localhost:6379")

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.saga

    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self):
        """Test health check when not initialized."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="redis://localhost:6379")
        health = await manager.health_check()

        assert health["status"] == "unhealthy"


class TestSQLiteStorageManager:
    """Tests for SQLite StorageManager configuration."""

    @pytest.mark.asyncio
    async def test_sqlite_memory_operations(self):
        """Test SQLite :memory: storage operations."""
        pytest.importorskip("aiosqlite")

        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.manager import StorageManager
        from sagaz.types import SagaStatus

        async with StorageManager(url="sqlite://:memory:") as manager:
            # Test saga operations
            await manager.saga.save_saga_state(
                saga_id="test-saga-1",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("test-saga-1")
            assert loaded is not None

            # Test outbox operations
            event = OutboxEvent(
                saga_id="test-saga-1",
                event_type="TestEvent",
                payload={},
            )
            await manager.outbox.insert(event)

            loaded_event = await manager.outbox.get_by_id(event.event_id)
            assert loaded_event is not None

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test health check returns healthy when initialized."""
        pytest.importorskip("aiosqlite")

        from sagaz.storage.manager import StorageManager

        async with StorageManager(url="sqlite://:memory:") as manager:
            health = await manager.health_check()

            assert health["status"] == "healthy"
            assert health["saga_backend"] == "sqlite"
            assert health["outbox_backend"] == "sqlite"


class TestStorageManagerExports:
    """Tests for module exports."""

    def test_exports_from_storage_module(self):
        """Test that StorageManager is exported from sagaz.storage."""
        from sagaz.storage import (
            BaseStorageManager,
            StorageManager,
            create_storage_manager,
        )

        assert BaseStorageManager is not None
        assert StorageManager is not None
        assert create_storage_manager is not None


class TestHybridMode:
    """Tests for hybrid mode (different backends for saga and outbox)."""

    def test_create_hybrid_manager(self):
        """Test creating hybrid manager with different URLs."""
        from sagaz.storage.manager import create_storage_manager

        manager = create_storage_manager(
            saga_url="memory://",
            outbox_url="memory://",
        )

        # Not actually hybrid since both are memory, but tests the API
        assert manager is not None

    def test_is_hybrid_same_backend(self):
        """Test is_hybrid returns False for same backend."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        assert manager.is_hybrid is False

    def test_is_hybrid_different_backend(self):
        """Test is_hybrid returns True for different backends."""
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(
            saga_url="postgresql://localhost/db",
            outbox_url="redis://localhost:6379",
        )
        assert manager.is_hybrid is True

    @pytest.mark.asyncio
    async def test_hybrid_health_check_shows_different_backends(self):
        """Test health check shows different backends in hybrid mode."""
        from sagaz.storage.manager import StorageManager

        # Both memory, but using saga_url and outbox_url
        manager = StorageManager(
            saga_url="memory://",
            outbox_url="memory://",
        )
        await manager.initialize()

        try:
            health = await manager.health_check()

            assert health["saga_backend"] == "memory"
            assert health["outbox_backend"] == "memory"
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_hybrid_sqlite_saga_and_outbox(self):
        """Test hybrid mode with SQLite for both (but separate URLs triggers hybrid path)."""
        pytest.importorskip("aiosqlite")

        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.manager import StorageManager
        from sagaz.types import SagaStatus

        manager = StorageManager(
            saga_url="sqlite://:memory:",
            outbox_url="sqlite://:memory:",
        )
        await manager.initialize()

        try:
            # Test saga storage
            await manager.saga.save_saga_state(
                saga_id="hybrid-test-1",
                saga_name="HybridSaga",
                status=SagaStatus.EXECUTING,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("hybrid-test-1")
            assert loaded is not None

            # Test outbox storage
            event = OutboxEvent(
                saga_id="hybrid-test-1",
                event_type="TestEvent",
                payload={},
            )
            await manager.outbox.insert(event)

            loaded_event = await manager.outbox.get_by_id(event.event_id)
            assert loaded_event is not None
        finally:
            await manager.close()



class TestSagaConfigIntegration:
    """Tests for SagaConfig integration with StorageManager."""

    @pytest.mark.asyncio
    async def test_saga_config_with_storage_manager(self):
        """Test SagaConfig accepts storage_manager parameter."""
        from sagaz.config import SagaConfig
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        await manager.initialize()

        try:
            config = SagaConfig(storage_manager=manager)

            # Storage should be extracted from manager
            assert config.storage is manager.saga
            assert config.outbox_storage is manager.outbox
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_saga_config_cannot_mix_manager_with_storage(self):
        """Test SagaConfig raises error if both storage_manager and storage provided."""
        from sagaz.config import SagaConfig
        from sagaz.storage.manager import StorageManager
        from sagaz.storage.memory import InMemorySagaStorage

        manager = StorageManager(url="memory://")
        await manager.initialize()

        try:
            with pytest.raises(ValueError, match="Cannot specify both"):
                SagaConfig(
                    storage_manager=manager,
                    storage=InMemorySagaStorage(),
                )
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_saga_config_cannot_mix_manager_with_outbox_storage(self):
        """Test SagaConfig raises error if both storage_manager and outbox_storage provided."""
        from sagaz.config import SagaConfig
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        await manager.initialize()

        try:
            with pytest.raises(ValueError, match="Cannot specify both"):
                SagaConfig(
                    storage_manager=manager,
                    outbox_storage=InMemoryOutboxStorage(),
                )
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_saga_config_manager_not_initialized_warning(self):
        """Test SagaConfig warns if manager not initialized."""
        from sagaz.config import SagaConfig
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        # Don't initialize

        with pytest.warns(match="not initialized") if hasattr(pytest, "warns") else nullcontext():
            config = SagaConfig(storage_manager=manager)

        # Should fall back to default storage
        assert config.storage is not None
        # No need to close - manager was never initialized

    @pytest.mark.asyncio
    async def test_saga_config_manager_with_broker(self):
        """Test SagaConfig with storage_manager and broker."""
        from sagaz.config import SagaConfig
        from sagaz.outbox.brokers.memory import InMemoryBroker
        from sagaz.storage.manager import StorageManager

        manager = StorageManager(url="memory://")
        await manager.initialize()
        broker = InMemoryBroker()

        try:
            config = SagaConfig(storage_manager=manager, broker=broker)

            # Should use outbox from manager, not derive it
            assert config._derived_outbox_storage is manager.outbox
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_saga_with_storage_manager(self):
        """Test running a saga with StorageManager configuration."""
        from sagaz import Saga, action, configure
        from sagaz.config import SagaConfig
        from sagaz.storage.manager import StorageManager
        from sagaz.types import SagaStatus

        manager = StorageManager(url="memory://")
        await manager.initialize()

        config = SagaConfig(storage_manager=manager, logging=False, metrics=False)

        class TestSaga(Saga):
            saga_name = "test-saga"

            @action("do_thing")
            async def do_thing(self, ctx):
                return {"done": True}

        # Configure globally
        configure(config)

        try:
            saga = TestSaga()
            result = await saga.run({})

            assert result.get("done") is True
        finally:
            # Reset global config
            from sagaz.config import _global_config
            if _global_config is config:
                configure(SagaConfig())  # Reset to default
            await manager.close()


# Helper for Python versions without pytest.warns contextmanager support
from contextlib import contextmanager, nullcontext


@contextmanager
def nullcontext():
    """No-op context manager for fallback."""
    yield

