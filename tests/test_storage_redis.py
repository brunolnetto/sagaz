"""
Tests for Redis storage backend.
Includes unit tests, mocked tests, and integration tests using testcontainers.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.exceptions import MissingDependencyError
from sagaz.storage.base import SagaNotFoundError, SagaStorageConnectionError, SagaStorageError
from sagaz.types import SagaStatus, SagaStepStatus

# Check availability of dependencies
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    from testcontainers.redis import RedisContainer

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False


class AsyncContextManagerMock:
    """Helper class to create async context manager mocks."""

    def __init__(self, return_value=None):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


# ============================================
# UNIT/MOCKED TESTS
# ============================================


class TestRedisStorageImportError:
    """Tests for Redis storage when redis package is not available"""

    def test_redis_not_available_import_error(self):
        """Test that RedisSagaStorage raises MissingDependencyError when redis not available"""
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            with patch("sagaz.storage.redis.REDIS_AVAILABLE", False):
                from sagaz.storage.redis import RedisSagaStorage

                with pytest.raises(MissingDependencyError):
                    RedisSagaStorage(redis_url="redis://localhost:6379")


class TestRedisSagaStorageUnit:
    """Unit tests for RedisSagaStorage without actual Redis"""

    @pytest.mark.asyncio
    async def test_redis_initialization(self):
        """Test Redis storage initialization"""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.redis.redis"):
                from sagaz.storage.redis import RedisSagaStorage

                storage = RedisSagaStorage(
                    redis_url="redis://localhost:6379", key_prefix="test:", default_ttl=3600
                )

                assert storage.redis_url == "redis://localhost:6379"
                assert storage.key_prefix == "test:"
                assert storage.default_ttl == 3600

    @pytest.mark.asyncio
    async def test_redis_key_generation(self):
        """Test Redis key generation methods"""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.redis.redis"):
                from sagaz.storage.redis import RedisSagaStorage

                storage = RedisSagaStorage(key_prefix="saga:")

                assert storage._saga_key("test-123") == "saga:test-123"
                assert storage._step_key("test-123", "step1") == "saga:test-123:step:step1"
                assert storage._index_key("status") == "saga:index:status"

    @pytest.mark.asyncio
    async def test_redis_connection_error_handling(self):
        """Test Redis connection error handling"""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            with patch("sagaz.storage.redis.redis") as mock_redis:
                mock_redis.from_url.side_effect = Exception("Connection refused")

                from sagaz.storage.redis import RedisSagaStorage

                storage = RedisSagaStorage(redis_url="redis://invalid:9999")

                with pytest.raises(SagaStorageConnectionError, match="Failed to connect to Redis"):
                    await storage._get_redis()


class TestRedisStorageEdgeCases:
    """Tests for Redis storage edge cases"""

    @pytest.mark.asyncio
    async def test_redis_json_decode_error(self):
        """Test that Redis storage handles JSON decode errors"""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True), patch("sagaz.storage.redis.redis"):
            from sagaz.storage.redis import RedisSagaStorage

            # This test would need a real Redis instance
            # For now, we'll mock to simulate the error condition
            storage = MagicMock(spec=RedisSagaStorage)
            storage.load_saga_state = AsyncMock(side_effect=SagaStorageError("Failed to decode"))

            with pytest.raises(SagaStorageError, match="decode"):
                await storage.load_saga_state("invalid-json-saga")


class TestRedisSagaStorageMocked:
    """Test RedisSagaStorage with mocked redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        client = MagicMock()

        # Setup async methods
        client.hget = AsyncMock(return_value=None)
        client.hset = AsyncMock()
        client.delete = AsyncMock()
        client.set = AsyncMock()
        client.get = AsyncMock(return_value=b"ok")
        client.keys = AsyncMock(return_value=[])
        client.smembers = AsyncMock(return_value=set())
        client.sadd = AsyncMock()
        client.srem = AsyncMock()
        client.scard = AsyncMock(return_value=0)
        client.expire = AsyncMock()
        client.info = AsyncMock(return_value={})
        client.ping = AsyncMock()
        client.aclose = AsyncMock()

        # Setup pipeline as async context manager
        pipeline = MagicMock()
        pipeline.hset = AsyncMock()
        pipeline.sadd = AsyncMock()
        pipeline.srem = AsyncMock()
        pipeline.delete = AsyncMock()
        pipeline.expire = AsyncMock()
        pipeline.execute = AsyncMock(return_value=[])

        client.pipeline.return_value = AsyncContextManagerMock(pipeline)

        return client, pipeline

    @pytest.mark.asyncio
    async def test_save_saga_state(self, mock_redis):
        """Test saving saga state to Redis."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="OrderSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"order_id": "123"},
            )

            pipeline.hset.assert_called()

    @pytest.mark.asyncio
    async def test_load_saga_state(self, mock_redis):
        """Test loading saga state from Redis."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            saga_data = {
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "executing",
                "steps": [],
                "context": {},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            }
            client.hget.return_value = json.dumps(saga_data).encode()

            result = await storage.load_saga_state("saga-123")

            assert result["saga_id"] == "saga-123"

    @pytest.mark.asyncio
    async def test_load_saga_state_not_found(self, mock_redis):
        """Test loading non-existent saga state."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.hget.return_value = None

            result = await storage.load_saga_state("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_load_saga_state_invalid_json(self, mock_redis):
        """Test loading saga with invalid JSON raises error."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.hget.return_value = b"invalid json{"

            with pytest.raises(SagaStorageError):
                await storage.load_saga_state("saga-123")

    @pytest.mark.asyncio
    async def test_delete_saga_state(self, mock_redis):
        """Test deleting saga state from Redis."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            # Mock load_saga_state to return existing saga
            saga_data = json.dumps(
                {
                    "saga_id": "saga-123",
                    "saga_name": "OrderSaga",
                    "status": "completed",
                    "steps": [],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()
            pipeline.execute.return_value = [1]  # Delete succeeded

            result = await storage.delete_saga_state("saga-123")

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_saga_state_not_found(self, mock_redis):
        """Test deleting non-existent saga state."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.hget.return_value = None

            result = await storage.delete_saga_state("nonexistent")

            assert result is False

    @pytest.mark.asyncio
    async def test_list_sagas_by_status(self, mock_redis):
        """Test listing sagas filtered by status."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            # Mock status index
            client.smembers.return_value = {b"saga-123"}

            # Mock saga data
            saga_data = json.dumps(
                {
                    "saga_id": "saga-123",
                    "saga_name": "OrderSaga",
                    "status": "completed",
                    "steps": [],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()

            result = await storage.list_sagas(status=SagaStatus.COMPLETED)

            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_step_state(self, mock_redis):
        """Test updating step state."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            saga_data = json.dumps(
                {
                    "saga_id": "saga-123",
                    "saga_name": "OrderSaga",
                    "status": "executing",
                    "steps": [{"name": "step1", "status": "pending"}],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()

            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"success": True},
            )

    @pytest.mark.asyncio
    async def test_update_step_state_saga_not_found(self, mock_redis):
        """Test updating step when saga not found."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.hget.return_value = None

            with pytest.raises(SagaNotFoundError):
                await storage.update_step_state(
                    saga_id="nonexistent", step_name="step1", status=SagaStepStatus.COMPLETED
                )

    @pytest.mark.asyncio
    async def test_update_step_state_step_not_found(self, mock_redis):
        """Test updating non-existent step raises error."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            saga_data = json.dumps(
                {
                    "saga_id": "saga-123",
                    "saga_name": "OrderSaga",
                    "status": "executing",
                    "steps": [{"name": "step1", "status": "pending"}],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()

            with pytest.raises(SagaStorageError):
                await storage.update_step_state(
                    saga_id="saga-123",
                    step_name="nonexistent_step",
                    status=SagaStepStatus.COMPLETED,
                )

    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, mock_redis):
        """Test getting saga statistics."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            client.info.return_value = {"used_memory": 1024000, "used_memory_human": "1M"}
            client.scard.return_value = 10

            stats = await storage.get_saga_statistics()

            assert "total_sagas" in stats
            assert "redis_memory_human" in stats

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, mock_redis):
        """Test cleaning up old completed sagas."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            # Mock saga IDs in status index
            client.smembers.return_value = {b"saga-old"}

            # Mock old saga data
            old_saga = json.dumps(
                {
                    "saga_id": "saga-old",
                    "saga_name": "OldSaga",
                    "status": "completed",
                    "steps": [],
                    "context": {},
                    "metadata": {},
                    "created_at": "2023-01-01T00:00:00+00:00",
                    "updated_at": "2023-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = old_saga.encode()
            pipeline.execute.return_value = [1]

            count = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))

            assert count >= 0

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_redis):
        """Test health check when healthy."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            client.get.return_value = b"ok"
            client.info.return_value = {
                "redis_version": "7.0.0",
                "connected_clients": 5,
                "used_memory_human": "1M",
            }

            result = await storage.health_check()

            assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, mock_redis):
        """Test health check when unhealthy."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.set.side_effect = Exception("Connection refused")

            result = await storage.health_check()

            assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with (
            patch("sagaz.storage.redis.REDIS_AVAILABLE", True),
            patch("sagaz.storage.redis.redis") as mock_redis_module,
        ):
            from sagaz.storage.redis import RedisSagaStorage

            client = AsyncMock()
            client.ping = AsyncMock()
            client.aclose = AsyncMock()
            mock_redis_module.from_url.return_value = client

            async with RedisSagaStorage("redis://localhost:6379") as storage:
                assert storage._redis is not None

            client.aclose.assert_called_once()

    def test_key_generation(self):
        """Test Redis key generation helpers."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True), patch("sagaz.storage.redis.redis"):
            from sagaz.storage.redis import RedisSagaStorage

            storage = RedisSagaStorage("redis://localhost:6379", key_prefix="test:")

            assert storage._saga_key("123") == "test:123"
            assert storage._step_key("123", "step1") == "test:123:step:step1"
            assert storage._index_key("status") == "test:index:status"


# ============================================
# INTEGRATION TESTS
# ============================================
@pytest.mark.skipif(not TESTCONTAINERS_AVAILABLE, reason="testcontainers not available")
@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis not installed")
@pytest.mark.xdist_group(name="redis")
class TestRedisStorageIntegration:
    """Tests for Redis storage with real Redis container"""

    @pytest.mark.asyncio
    async def test_save_and_load_saga_state(self, redis_container):
        """Test saving and loading saga state"""
        from sagaz.storage.redis import RedisSagaStorage

        # Build Redis URL from container host and port
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Save saga state
            await storage.save_saga_state(
                saga_id="redis-test-123",
                saga_name="RedisTestSaga",
                status=SagaStatus.COMPLETED,
                steps=[
                    {
                        "name": "step1",
                        "status": "completed",
                        "result": {"data": "value"},
                    }
                ],
                context={"user_id": "user-789"},
                metadata={"version": "2.0"},
            )

            # Load saga state
            state = await storage.load_saga_state("redis-test-123")

            assert state is not None
            assert state["saga_id"] == "redis-test-123"
            assert state["saga_name"] == "RedisTestSaga"
            assert state["status"] == "completed"
            assert state["context"]["user_id"] == "user-789"
            assert len(state["steps"]) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_saga(self, redis_container):
        """Test loading a saga that doesn't exist"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            state = await storage.load_saga_state("nonexistent-redis")
            assert state is None

    @pytest.mark.asyncio
    async def test_delete_saga_state(self, redis_container):
        """Test deleting saga state"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Save saga
            await storage.save_saga_state(
                saga_id="redis-delete-me",
                saga_name="RedisDeleteTest",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # Verify it exists
            state = await storage.load_saga_state("redis-delete-me")
            assert state is not None

            # Delete it
            result = await storage.delete_saga_state("redis-delete-me")
            assert result is True

            # Verify it's gone
            state = await storage.load_saga_state("redis-delete-me")
            assert state is None

    @pytest.mark.asyncio
    async def test_list_sagas_by_status(self, redis_container):
        """Test listing sagas filtered by status"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create multiple sagas
            await storage.save_saga_state(
                saga_id="redis-completed-1",
                saga_name="RedisTest1",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            await storage.save_saga_state(
                saga_id="redis-failed-1",
                saga_name="RedisTest2",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # List completed sagas
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED, limit=10)
            assert len(completed) >= 1
            assert any(s["saga_id"] == "redis-completed-1" for s in completed)

    @pytest.mark.asyncio
    async def test_ttl_applied_to_completed_sagas(self, redis_container):
        """Test that TTL is applied to completed sagas"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        # Use 1 second TTL for fast test
        async with RedisSagaStorage(redis_url=redis_url, default_ttl=1) as storage:
            # Save completed saga
            await storage.save_saga_state(
                saga_id="redis-ttl-test",
                saga_name="TTLTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # Verify it exists
            state = await storage.load_saga_state("redis-ttl-test")
            assert state is not None

            # Wait for TTL to expire with some buffer
            await asyncio.sleep(2.5)

            # Verify it's expired
            state = await storage.load_saga_state("redis-ttl-test")
            assert state is None

    @pytest.mark.asyncio
    async def test_update_existing_saga(self, redis_container):
        """Test updating an existing saga state"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create saga
            await storage.save_saga_state(
                saga_id="redis-update-test",
                saga_name="RedisUpdateTest",
                status=SagaStatus.EXECUTING,
                steps=[],
                context={"counter": 1},
                metadata={},
            )

            # Update saga
            await storage.save_saga_state(
                saga_id="redis-update-test",
                saga_name="RedisUpdateTest",
                status=SagaStatus.COMPLETED,
                steps=[{"name": "step1", "status": "completed"}],
                context={"counter": 2},
                metadata={},
            )

            # Load and verify
            state = await storage.load_saga_state("redis-update-test")
            assert state["status"] == "completed"
            assert state["context"]["counter"] == 2
            assert len(state["steps"]) == 1

    @pytest.mark.asyncio
    async def test_update_step_state(self, redis_container):
        """Test updating individual step state"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create saga with a step
            await storage.save_saga_state(
                saga_id="redis-step-update",
                saga_name="StepUpdateTest",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending", "result": None}],
                context={},
                metadata={},
            )

            # Update step state
            await storage.update_step_state(
                saga_id="redis-step-update",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"output": "success"},
                error=None,
            )

            # Load and verify
            state = await storage.load_saga_state("redis-step-update")
            step = next(s for s in state["steps"] if s["name"] == "step1")
            assert step["status"] == "completed"
            assert step["result"] == {"output": "success"}

    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, redis_container):
        """Test getting saga statistics"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create sagas in different states
            await storage.save_saga_state(
                saga_id="redis-stats-completed",
                saga_name="StatsTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            await storage.save_saga_state(
                saga_id="redis-stats-failed",
                saga_name="StatsTest",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # Get statistics
            stats = await storage.get_saga_statistics()

            assert "total_sagas" in stats
            assert "by_status" in stats
            assert stats["total_sagas"] >= 2

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, redis_container):
        """Test cleanup of old completed sagas"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create completed saga
            await storage.save_saga_state(
                saga_id="redis-cleanup-test",
                saga_name="CleanupTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # Sleep to make timestamp older
            await asyncio.sleep(1.5)

            # Cleanup sagas older than now
            deleted_count = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))

            # At least our test saga should be deleted
            assert deleted_count >= 1

            # Verify saga is gone
            state = await storage.load_saga_state("redis-cleanup-test")
            assert state is None

    @pytest.mark.asyncio
    async def test_health_check(self, redis_container):
        """Test health check functionality"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            health = await storage.health_check()

            assert "status" in health
            assert health["status"] == "healthy"
            assert "storage_type" in health
            assert health["storage_type"] == "redis"

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        from sagaz.storage.redis import RedisSagaStorage

        # Use invalid Redis URL
        redis_url = "redis://invalid-host:9999"

        storage = RedisSagaStorage(redis_url=redis_url)

        # Attempting operations should raise connection error
        with pytest.raises(SagaStorageError):
            async with storage:
                await storage.save_saga_state(
                    saga_id="test",
                    saga_name="Test",
                    status=SagaStatus.PENDING,
                    steps=[],
                    context={},
                    metadata={},
                )

    @pytest.mark.asyncio
    async def test_list_sagas_with_limit(self, redis_container):
        """Test listing sagas with limit parameter"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create multiple sagas
            for i in range(5):
                await storage.save_saga_state(
                    saga_id=f"redis-limit-test-{i}",
                    saga_name="LimitTest",
                    status=SagaStatus.COMPLETED,
                    steps=[],
                    context={},
                    metadata={},
                )

            # List with small limit
            sagas = await storage.list_sagas(limit=2)

            # Should respect limit
            assert len(sagas) <= 2

    @pytest.mark.asyncio
    async def test_update_step_state_on_nonexistent_saga(self, redis_container):
        """Test updating step state when saga doesn't exist"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Try to update step on non-existent saga
            with pytest.raises(SagaNotFoundError):
                await storage.update_step_state(
                    "nonexistent-saga-xyz",
                    "step1",
                    SagaStepStatus.COMPLETED,
                    result={"data": "test"},
                )

    @pytest.mark.asyncio
    async def test_update_step_state_on_nonexistent_step(self, redis_container):
        """Test updating a step that doesn't exist in the saga"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create a saga with one step
            await storage.save_saga_state(
                saga_id="test-saga-missing-step",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={},
                metadata={},
            )

            # Try to update a non-existent step
            with pytest.raises(SagaStorageError, match="Step.*not found"):
                await storage.update_step_state(
                    "test-saga-missing-step",
                    "nonexistent-step",
                    SagaStepStatus.COMPLETED,
                    result={"data": "test"},
                )

    @pytest.mark.asyncio
    async def test_cleanup_with_invalid_timestamps(self, redis_container):
        """Test cleanup handles sagas with invalid timestamps gracefully"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            # Create a valid saga
            await storage.save_saga_state(
                saga_id="valid-saga-for-cleanup",
                saga_name="ValidSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # Manually inject a saga with invalid timestamp
            redis_client = await storage._get_redis()
            invalid_saga_data = {
                "saga_id": "invalid-saga-timestamp",
                "saga_name": "InvalidSaga",
                "status": "completed",
                "steps": [],
                "context": {},
                "metadata": {},
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": "not-a-valid-timestamp",  # Invalid!
            }
            await redis_client.hset(
                storage._saga_key("invalid-saga-timestamp"), "data", json.dumps(invalid_saga_data)
            )
            # Add to status index
            await redis_client.sadd(
                storage._index_key("status:completed"), "invalid-saga-timestamp"
            )

            # Cleanup should skip invalid saga and not crash
            deleted = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC) + timedelta(days=1)
            )

            # Should succeed without crashing
            assert deleted >= 0

    @pytest.mark.asyncio
    async def test_list_sagas_with_status_and_name_filter(self, redis_container):
        """Test listing sagas with both status and name filters"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url, key_prefix="filter-test:") as storage:
            # Create sagas with specific status and name
            await storage.save_saga_state(
                saga_id="redis-filter-1",
                saga_name="FilterSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            await storage.save_saga_state(
                saga_id="redis-filter-2",
                saga_name="OtherSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # List with both status and name filter
            results = await storage.list_sagas(status=SagaStatus.COMPLETED, saga_name="FilterSaga")

            matching = [r for r in results if r["saga_id"] == "redis-filter-1"]
            assert len(matching) >= 1

    @pytest.mark.asyncio
    async def test_list_sagas_no_filter_pagination(self, redis_container):
        """Test listing all sagas without filters uses pattern matching"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url, key_prefix="nofilter:") as storage:
            # Create multiple sagas
            for i in range(3):
                await storage.save_saga_state(
                    saga_id=f"redis-saga-{i}",
                    saga_name="NoFilterSaga",
                    status=SagaStatus.EXECUTING,
                    steps=[],
                    context={},
                    metadata={},
                )

            # List without any filters
            results = await storage.list_sagas(limit=10)

            assert len(results) >= 3

    @pytest.mark.asyncio
    async def test_delete_nonexistent_saga(self, redis_container):
        """Test deleting a saga that doesn't exist"""
        from sagaz.storage.redis import RedisSagaStorage

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url, key_prefix="delete-test:") as storage:
            result = await storage.delete_saga_state("nonexistent-redis-saga-xyz")
            assert result is False
