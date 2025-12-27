"""
Integration tests for storage backends using testcontainers.

These tests run against real PostgreSQL and Redis containers to verify
the storage implementations work correctly with actual databases.

Requires Docker to be running.
"""

from datetime import datetime

import pytest

# Check if testcontainers is available
try:
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

# Check for asyncpg
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

# Check for redis
try:
    import redis.asyncio

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# ============================================
# POSTGRESQL INTEGRATION TESTS
# ============================================

# Note: postgres_container fixture is now defined in conftest.py
# with session scope for better performance (shared across all tests)


@pytest.fixture
async def pg_storage(postgres_container):
    """Create PostgreSQL storage instance."""
    if not ASYNCPG_AVAILABLE:
        pytest.skip("asyncpg not available")

    from sagaz.storage.postgresql import PostgreSQLSagaStorage

    conn_string = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )

    storage = PostgreSQLSagaStorage(conn_string)

    # Initialize tables
    await storage._get_pool()

    yield storage

    # Cleanup
    if storage._pool:
        await storage._pool.close()


@pytest.mark.integration
@pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers not available")
@pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="asyncpg not available")
@pytest.mark.xdist_group(name="postgres")
class TestPostgreSQLIntegration:
    """Integration tests for PostgreSQL storage."""

    @pytest.mark.asyncio
    async def test_save_and_load_saga(self, pg_storage):
        """Test saving and loading saga state."""
        from sagaz.types import SagaStatus

        saga_id = f"test-saga-{datetime.now().timestamp()}"

        await pg_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="TestSaga",
            status=SagaStatus.EXECUTING,
            steps=[
                {"name": "step1", "status": "pending"},
                {"name": "step2", "status": "pending"},
            ],
            context={"order_id": "ORD-123"},
            metadata={"version": 1},
        )

        loaded = await pg_storage.load_saga_state(saga_id)

        assert loaded is not None
        assert loaded["saga_id"] == saga_id
        assert loaded["saga_name"] == "TestSaga"
        assert loaded["status"] == "executing"
        assert len(loaded["steps"]) == 2
        assert loaded["context"]["order_id"] == "ORD-123"

    @pytest.mark.asyncio
    async def test_update_saga_state(self, pg_storage):
        """Test updating saga state."""
        from sagaz.types import SagaStatus

        saga_id = f"update-saga-{datetime.now().timestamp()}"

        # Create saga
        await pg_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="UpdateSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={},
        )

        # Update saga
        await pg_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="UpdateSaga",
            status=SagaStatus.COMPLETED,
            steps=[{"name": "step1", "status": "completed"}],
            context={"result": "success"},
        )

        loaded = await pg_storage.load_saga_state(saga_id)

        assert loaded["status"] == "completed"
        assert loaded["context"]["result"] == "success"

    @pytest.mark.asyncio
    async def test_delete_saga(self, pg_storage):
        """Test deleting saga state."""
        from sagaz.types import SagaStatus

        saga_id = f"delete-saga-{datetime.now().timestamp()}"

        await pg_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="DeleteSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        result = await pg_storage.delete_saga_state(saga_id)
        assert result is True

        loaded = await pg_storage.load_saga_state(saga_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_sagas(self, pg_storage):
        """Test listing sagas."""
        from sagaz.types import SagaStatus

        # Create some sagas
        for i in range(3):
            await pg_storage.save_saga_state(
                saga_id=f"list-saga-{i}-{datetime.now().timestamp()}",
                saga_name="ListSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

        sagas = await pg_storage.list_sagas(saga_name="ListSaga", limit=10)

        assert len(sagas) >= 3

    @pytest.mark.asyncio
    async def test_health_check(self, pg_storage):
        """Test health check."""
        result = await pg_storage.health_check()

        assert result["status"] == "healthy"
        assert result["storage_type"] == "postgresql"

    @pytest.mark.asyncio
    async def test_get_statistics(self, pg_storage):
        """Test getting statistics."""
        stats = await pg_storage.get_saga_statistics()

        assert "total_sagas" in stats
        assert "by_status" in stats
        assert "database_size_bytes" in stats


# ============================================
# REDIS INTEGRATION TESTS
# ============================================

# Note: redis_container fixture is now defined in conftest.py
# with session scope for better performance (shared across all tests)


@pytest.fixture
async def redis_storage(redis_container):
    """Create Redis storage instance."""
    if not REDIS_AVAILABLE:
        pytest.skip("redis not available")

    from sagaz.storage.redis import RedisSagaStorage

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)

    storage = RedisSagaStorage(
        redis_url=f"redis://{host}:{port}", key_prefix=f"test-{datetime.now().timestamp()}:"
    )

    # Initialize connection
    await storage._get_redis()

    yield storage

    # Cleanup
    if storage._redis:
        await storage._redis.aclose()


@pytest.mark.integration
@pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers not available")
@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis not available")
@pytest.mark.xdist_group(name="redis")
class TestRedisIntegration:
    """Integration tests for Redis storage."""

    @pytest.mark.asyncio
    async def test_save_and_load_saga(self, redis_storage):
        """Test saving and loading saga state."""
        from sagaz.types import SagaStatus

        saga_id = f"redis-saga-{datetime.now().timestamp()}"

        await redis_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="RedisSaga",
            status=SagaStatus.EXECUTING,
            steps=[
                {"name": "step1", "status": "pending"},
            ],
            context={"data": "test"},
        )

        loaded = await redis_storage.load_saga_state(saga_id)

        assert loaded is not None
        assert loaded["saga_id"] == saga_id
        assert loaded["saga_name"] == "RedisSaga"
        assert loaded["context"]["data"] == "test"

    @pytest.mark.asyncio
    async def test_update_step_state(self, redis_storage):
        """Test updating step state."""
        from sagaz.types import SagaStatus, SagaStepStatus

        saga_id = f"step-update-{datetime.now().timestamp()}"

        await redis_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="StepSaga",
            status=SagaStatus.EXECUTING,
            steps=[{"name": "step1", "status": "pending"}],
            context={},
        )

        await redis_storage.update_step_state(
            saga_id=saga_id,
            step_name="step1",
            status=SagaStepStatus.COMPLETED,
            result={"success": True},
        )

        loaded = await redis_storage.load_saga_state(saga_id)

        assert loaded["steps"][0]["status"] == "completed"
        assert loaded["steps"][0]["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_delete_saga(self, redis_storage):
        """Test deleting saga state."""
        from sagaz.types import SagaStatus

        saga_id = f"delete-redis-{datetime.now().timestamp()}"

        await redis_storage.save_saga_state(
            saga_id=saga_id,
            saga_name="DeleteSaga",
            status=SagaStatus.COMPLETED,
            steps=[],
            context={},
        )

        result = await redis_storage.delete_saga_state(saga_id)
        assert result is True

        loaded = await redis_storage.load_saga_state(saga_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_health_check(self, redis_storage):
        """Test health check."""
        result = await redis_storage.health_check()

        assert result["status"] == "healthy"
        assert result["storage_type"] == "redis"

    @pytest.mark.asyncio
    async def test_get_statistics(self, redis_storage):
        """Test getting statistics."""
        stats = await redis_storage.get_saga_statistics()

        assert "total_sagas" in stats
        assert "by_status" in stats
        assert "redis_memory_human" in stats


# ============================================
# REDIS BROKER INTEGRATION TESTS
# ============================================


@pytest.fixture
async def redis_broker(redis_container):
    """Create Redis broker instance."""
    if not REDIS_AVAILABLE:
        pytest.skip("redis not available")

    from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)

    config = RedisBrokerConfig(
        url=f"redis://{host}:{port}", stream_name=f"test-stream-{datetime.now().timestamp()}"
    )

    broker = RedisBroker(config)
    await broker.connect()

    yield broker

    await broker.close()


@pytest.mark.integration
@pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers not available")
@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis not available")
@pytest.mark.xdist_group(name="redis")
class TestRedisBrokerIntegration:
    """Integration tests for Redis broker."""

    @pytest.mark.asyncio
    async def test_publish_message(self, redis_broker):
        """Test publishing a message."""
        await redis_broker.publish(
            topic="test.event",
            message=b'{"order_id": "123"}',
            headers={"trace_id": "abc"},
            key="order-123",
        )

        # Should not raise

    @pytest.mark.asyncio
    async def test_ensure_consumer_group(self, redis_broker):
        """Test creating consumer group."""
        await redis_broker.ensure_consumer_group()

        # Should not raise

    @pytest.mark.asyncio
    async def test_get_stream_info(self, redis_broker):
        """Test getting stream info."""
        # Publish a message first
        await redis_broker.publish("test", b"data")

        info = await redis_broker.get_stream_info()

        assert info["length"] >= 1

    @pytest.mark.asyncio
    async def test_health_check(self, redis_broker):
        """Test health check."""
        is_healthy = await redis_broker.health_check()

        assert is_healthy is True
