"""
Integration tests for StorageManager with testcontainers.

Targets storage/manager.py coverage gaps by exercising real PostgreSQL and Redis
initialization paths.

Run with:
    pytest -m integration tests/integration/test_storage_manager_integration.py -v --timeout=120
"""

import asyncio

import pytest

pytest.importorskip("testcontainers")

# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(60),  # 60 second timeout per test
]


class TestStorageManagerPostgreSQLIntegration:
    """Integration tests for StorageManager with PostgreSQL backend."""

    @pytest.mark.asyncio
    async def test_postgresql_unified_storage_manager(self, postgres_container):
        """Test StorageManager with PostgreSQL for both saga and outbox."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        pytest.importorskip("asyncpg")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        manager = StorageManager(url=conn_string)
        await manager.initialize()

        try:
            # Verify storages are initialized
            assert manager.saga is not None
            assert manager.outbox is not None
            assert manager.is_hybrid is False

            # Test saga operations
            await manager.saga.save_saga_state(
                saga_id="pg-saga-test-1",
                saga_name="PostgreSQLTest",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"test": True},
            )

            loaded = await manager.saga.load_saga_state("pg-saga-test-1")
            assert loaded is not None
            assert loaded["saga_name"] == "PostgreSQLTest"

            # Test health check
            health = await manager.health_check()
            assert health["status"] == "healthy"
            assert health["saga_backend"] == "postgresql"
            assert health["outbox_backend"] == "postgresql"
            assert health["mode"] == "unified"

        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_postgresql_storage_manager_context_manager(self, postgres_container):
        """Test StorageManager with PostgreSQL using async context manager."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        pytest.importorskip("asyncpg")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with StorageManager(url=conn_string) as manager:
            # Save saga
            await manager.saga.save_saga_state(
                saga_id="pg-context-test-1",
                saga_name="ContextManagerTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            # Load and verify
            loaded = await manager.saga.load_saga_state("pg-context-test-1")
            assert loaded is not None


class TestStorageManagerRedisIntegration:
    """Integration tests for StorageManager with Redis backend."""

    @pytest.mark.asyncio
    async def test_redis_unified_storage_manager(self, redis_container):
        """Test StorageManager with Redis for both saga and outbox."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        pytest.importorskip("redis")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        manager = StorageManager(url=redis_url)
        await manager.initialize()

        try:
            # Verify storages are initialized
            assert manager.saga is not None
            assert manager.outbox is not None
            assert manager.is_hybrid is False

            # Test saga operations
            await manager.saga.save_saga_state(
                saga_id="redis-saga-test-1",
                saga_name="RedisTest",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"test": True},
            )

            loaded = await manager.saga.load_saga_state("redis-saga-test-1")
            assert loaded is not None
            assert loaded["saga_name"] == "RedisTest"

            # Test health check
            health = await manager.health_check()
            assert health["status"] == "healthy"
            assert health["saga_backend"] == "redis"
            assert health["outbox_backend"] == "redis"
            assert health["mode"] == "unified"

        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_redis_storage_manager_context_manager(self, redis_container):
        """Test StorageManager with Redis using async context manager."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        pytest.importorskip("redis")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with StorageManager(url=redis_url) as manager:
            # Save saga
            await manager.saga.save_saga_state(
                saga_id="redis-context-test-1",
                saga_name="ContextManagerTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            # Load and verify
            loaded = await manager.saga.load_saga_state("redis-context-test-1")
            assert loaded is not None


class TestStorageManagerHybridIntegration:
    """Integration tests for StorageManager in hybrid mode."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_hybrid_postgresql_redis_manager(
        self, postgres_container, redis_container
    ):
        """Test StorageManager with PostgreSQL for saga and Redis for outbox."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")
        if redis_container is None:
            pytest.skip("Redis container not available")

        pytest.importorskip("asyncpg")
        pytest.importorskip("redis")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus
        from sagaz.outbox.types import OutboxEvent

        pg_conn = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        redis_host = redis_container.get_container_host_ip()
        redis_port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{redis_host}:{redis_port}"

        manager = StorageManager(
            saga_url=pg_conn,
            outbox_url=redis_url,
        )
        await manager.initialize()

        try:
            # Verify hybrid mode
            assert manager.is_hybrid is True

            # Test saga storage (PostgreSQL)
            await manager.saga.save_saga_state(
                saga_id="hybrid-saga-test-1",
                saga_name="HybridTest",
                status=SagaStatus.EXECUTING,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("hybrid-saga-test-1")
            assert loaded is not None

            # Test outbox storage (Redis)
            event = OutboxEvent(
                saga_id="hybrid-saga-test-1",
                event_type="test.event",
                payload={"hybrid": True},
            )
            await manager.outbox.insert(event)

            retrieved = await manager.outbox.get_by_id(event.event_id)
            assert retrieved is not None

            # Test health check (shows both backends)
            health = await manager.health_check()
            assert health["saga_backend"] == "postgresql"
            assert health["outbox_backend"] == "redis"
            assert health["mode"] == "hybrid"

        finally:
            await manager.close()


class TestStorageManagerSQLiteIntegration:
    """Integration tests for StorageManager with SQLite backend."""

    @pytest.mark.asyncio
    async def test_sqlite_unified_storage_manager(self):
        """Test StorageManager with SQLite for both saga and outbox."""
        pytest.importorskip("aiosqlite")

        from sagaz.storage.manager import StorageManager
        from sagaz.core.types import SagaStatus

        async with StorageManager(url="sqlite://:memory:") as manager:
            # Verify storages are initialized
            assert manager.saga is not None
            assert manager.outbox is not None

            # Test saga operations
            await manager.saga.save_saga_state(
                saga_id="sqlite-saga-test-1",
                saga_name="SQLiteTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("sqlite-saga-test-1")
            assert loaded is not None
            assert loaded["saga_name"] == "SQLiteTest"

            # Health check
            health = await manager.health_check()
            assert health["status"] == "healthy"
            assert health["saga_backend"] == "sqlite"


class TestCreateStorageManagerFactoryIntegration:
    """Integration tests for create_storage_manager factory function."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_create_postgresql_manager(self, postgres_container):
        """Test creating manager from PostgreSQL URL."""
        if postgres_container is None:
            pytest.skip("PostgreSQL container not available")

        pytest.importorskip("asyncpg")

        from sagaz.storage.manager import create_storage_manager
        from sagaz.core.types import SagaStatus

        conn_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        manager = create_storage_manager(conn_string)
        await manager.initialize()

        try:
            await manager.saga.save_saga_state(
                saga_id="factory-pg-test-1",
                saga_name="FactoryTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("factory-pg-test-1")
            assert loaded is not None
        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_create_redis_manager(self, redis_container):
        """Test creating manager from Redis URL."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        pytest.importorskip("redis")

        from sagaz.storage.manager import create_storage_manager
        from sagaz.core.types import SagaStatus

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        manager = create_storage_manager(redis_url)
        await manager.initialize()

        try:
            await manager.saga.save_saga_state(
                saga_id="factory-redis-test-1",
                saga_name="FactoryTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            loaded = await manager.saga.load_saga_state("factory-redis-test-1")
            assert loaded is not None
        finally:
            await manager.close()

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_create_manager_with_backend_override(self, redis_container):
        """Test creating manager with explicit backend parameter."""
        if redis_container is None:
            pytest.skip("Redis container not available")

        pytest.importorskip("redis")

        from sagaz.storage.manager import create_storage_manager
        from sagaz.core.types import SagaStatus

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        # Use explicit backend=redis even though URL also indicates it
        manager = create_storage_manager(redis_url, backend="redis")
        await manager.initialize()

        try:
            health = await manager.health_check()
            assert health["saga_backend"] == "redis"
        finally:
            await manager.close()
