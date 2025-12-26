"""
Tests for PostgreSQL and Redis storage backends using testcontainers

These tests spin up real PostgreSQL and Redis containers to test
the storage implementations with actual database connections.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

# Skip entire module if testcontainers dependencies are not available
pytest.importorskip("testcontainers")

try:
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer
except ImportError:
    pytest.skip("testcontainers not available", allow_module_level=True)

try:
    import redis as redis_lib  # noqa: F401
except ImportError:
    pytest.skip("redis package not installed", allow_module_level=True)

try:
    import asyncpg  # noqa: F401
except ImportError:
    pytest.skip("asyncpg package not installed", allow_module_level=True)

from sagaz.storage.base import SagaNotFoundError, SagaStorageError
from sagaz.storage.postgresql import PostgreSQLSagaStorage
from sagaz.storage.redis import RedisSagaStorage
from sagaz.types import SagaStatus, SagaStepStatus


# Session-scoped fixtures - containers are expensive to start
# These are shared across the entire test session
@pytest.fixture(scope="session")
def postgres_container():
    """Fixture that provides a PostgreSQL container for the test session

    Note: Container startup takes ~25-30s. This is shared across all PostgreSQL tests.
    """
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    """Fixture that provides a Redis container for the test session

    Note: Container startup takes ~5-8s. This is shared across all Redis tests.
    """
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


# Mark to run storage tests sequentially to avoid container conflicts
# With pytest-xdist, group ensures all tests in this class run on same worker
@pytest.mark.xdist_group(name="postgres")
class TestPostgreSQLStorage:
    """Tests for PostgreSQL storage with real database"""

    @pytest.mark.asyncio
    async def test_save_and_load_saga_state(self, postgres_container):
        """Test saving and loading saga state"""
        # testcontainers returns postgresql+psycopg2://, but asyncpg expects postgresql://
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Save saga state
            await storage.save_saga_state(
                saga_id="test-123",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[
                    {
                        "name": "step1",
                        "status": "completed",
                        "result": {"data": "value"},
                        "error": None,
                        "retry_count": 0,
                    }
                ],
                context={"user_id": "user-456"},
                metadata={"version": "1.0"},
            )

            # Load saga state
            state = await storage.load_saga_state("test-123")

            assert state is not None
            assert state["saga_id"] == "test-123"
            assert state["saga_name"] == "TestSaga"
            assert state["status"] == "completed"  # Enum values are lowercase
            assert state["context"] == {"user_id": "user-456"}
            assert state["metadata"] == {"version": "1.0"}
            assert len(state["steps"]) == 1
            assert state["steps"][0]["name"] == "step1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_saga(self, postgres_container):
        """Test loading a saga that doesn't exist"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            state = await storage.load_saga_state("nonexistent")
            assert state is None

    @pytest.mark.asyncio
    async def test_delete_saga_state(self, postgres_container):
        """Test deleting saga state"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Save saga
            await storage.save_saga_state(
                saga_id="delete-me",
                saga_name="DeleteTest",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # Verify it exists
            state = await storage.load_saga_state("delete-me")
            assert state is not None

            # Delete it
            result = await storage.delete_saga_state("delete-me")
            assert result is True

            # Verify it's gone
            state = await storage.load_saga_state("delete-me")
            assert state is None

    @pytest.mark.asyncio
    async def test_list_sagas_by_status(self, postgres_container):
        """Test listing sagas filtered by status"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create multiple sagas
            await storage.save_saga_state(
                saga_id="completed-1",
                saga_name="Test1",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            await storage.save_saga_state(
                saga_id="failed-1",
                saga_name="Test2",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # List completed sagas
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED, limit=10)
            assert len(completed) >= 1
            assert any(s["saga_id"] == "completed-1" for s in completed)

            # List failed sagas
            failed = await storage.list_sagas(status=SagaStatus.FAILED, limit=10)
            assert len(failed) >= 1
            assert any(s["saga_id"] == "failed-1" for s in failed)

    @pytest.mark.asyncio
    async def test_list_sagas_by_name(self, postgres_container):
        """Test listing sagas filtered by name"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            await storage.save_saga_state(
                saga_id="unique-saga-123",
                saga_name="UniqueSagaName",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # List by name
            sagas = await storage.list_sagas(saga_name="UniqueSagaName", limit=10)
            assert len(sagas) >= 1
            assert any(s["saga_id"] == "unique-saga-123" for s in sagas)

    @pytest.mark.asyncio
    async def test_update_existing_saga(self, postgres_container):
        """Test updating an existing saga state"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create saga
            await storage.save_saga_state(
                saga_id="update-test",
                saga_name="UpdateTest",
                status=SagaStatus.EXECUTING,
                steps=[],
                context={"counter": 1},
                metadata={},
            )

            # Update saga
            await storage.save_saga_state(
                saga_id="update-test",
                saga_name="UpdateTest",
                status=SagaStatus.COMPLETED,
                steps=[
                    {
                        "name": "step1",
                        "status": "completed",
                        "result": None,
                        "error": None,
                        "retry_count": 0,
                    }
                ],
                context={"counter": 2},
                metadata={},
            )

            # Load and verify
            state = await storage.load_saga_state("update-test")
            assert state["status"] == "completed"  # Enum values are lowercase
            assert state["context"]["counter"] == 2
            assert len(state["steps"]) == 1

    @pytest.mark.asyncio
    async def test_update_step_state(self, postgres_container):
        """Test updating individual step state"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create saga with a step
            await storage.save_saga_state(
                saga_id="pg-step-update",
                saga_name="StepUpdateTest",
                status=SagaStatus.EXECUTING,
                steps=[
                    {
                        "name": "step1",
                        "status": "pending",
                        "result": None,
                        "error": None,
                        "retry_count": 0,
                    }
                ],
                context={},
                metadata={},
            )

            # Update step state
            await storage.update_step_state(
                saga_id="pg-step-update",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"output": "success"},
                error=None,
            )

            # Load and verify
            state = await storage.load_saga_state("pg-step-update")
            step = next(s for s in state["steps"] if s["name"] == "step1")
            assert step["status"] == "completed"
            assert step["result"] == {"output": "success"}

    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, postgres_container):
        """Test getting saga statistics"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create sagas in different states
            await storage.save_saga_state(
                saga_id="pg-stats-completed",
                saga_name="StatsTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            await storage.save_saga_state(
                saga_id="pg-stats-failed",
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
    async def test_cleanup_completed_sagas(self, postgres_container):
        """Test cleanup of old completed sagas"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create completed saga
            await storage.save_saga_state(
                saga_id="pg-cleanup-test",
                saga_name="CleanupTest",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
                metadata={},
            )

            # Cleanup sagas older than now (should delete immediately)
            from datetime import datetime, timedelta

            deleted_count = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC) + timedelta(seconds=1)
            )

            # At least our test saga should be deleted
            assert deleted_count >= 1

            # Verify saga is gone
            state = await storage.load_saga_state("pg-cleanup-test")
            assert state is None

    @pytest.mark.asyncio
    async def test_health_check(self, postgres_container):
        """Test health check functionality"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            health = await storage.health_check()

            assert "status" in health
            assert health["status"] == "healthy"
            assert "storage_type" in health
            assert health["storage_type"] == "postgresql"

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        # Use invalid PostgreSQL URL
        connection_string = "postgresql://invalid-user:invalid-pass@invalid-host:5432/invalid-db"

        storage = PostgreSQLSagaStorage(connection_string)

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
    async def test_list_sagas_pagination(self, postgres_container):
        """Test listing sagas with pagination"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create multiple sagas
            for i in range(5):
                await storage.save_saga_state(
                    saga_id=f"pg-pagination-test-{i}",
                    saga_name="PaginationTest",
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
    async def test_delete_nonexistent_saga(self, postgres_container):
        """Test deleting a saga that doesn't exist"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            result = await storage.delete_saga_state("nonexistent-saga-xyz")
            assert result is False

    @pytest.mark.asyncio
    async def test_save_and_load_with_executed_at_timestamp(self, postgres_container):
        """Test saving and loading saga with step timestamps (lines 198-201)"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            now = datetime.now(UTC)

            await storage.save_saga_state(
                saga_id="timestamp-test-pg",
                saga_name="TimestampTest",
                status=SagaStatus.COMPLETED,
                steps=[
                    {
                        "name": "step1",
                        "status": "completed",
                        "result": {"data": "value"},
                        "error": None,
                        "executed_at": now,
                        "compensated_at": now,
                        "retry_count": 0,
                    }
                ],
                context={},
                metadata={},
            )

            state = await storage.load_saga_state("timestamp-test-pg")

            assert state is not None
            assert state["steps"][0]["executed_at"] is not None
            assert state["steps"][0]["compensated_at"] is not None

    @pytest.mark.asyncio
    async def test_update_step_state_not_found(self, postgres_container):
        """Test updating step state when step doesn't exist (line 322)"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create a saga with one step
            await storage.save_saga_state(
                saga_id="pg-step-not-found-test",
                saga_name="StepNotFoundTest",
                status=SagaStatus.EXECUTING,
                steps=[
                    {
                        "name": "existing_step",
                        "status": "pending",
                        "result": None,
                        "error": None,
                        "retry_count": 0,
                    }
                ],
                context={},
                metadata={},
            )

            # Try to update a non-existent step
            with pytest.raises(SagaStorageError, match="not found"):
                await storage.update_step_state(
                    saga_id="pg-step-not-found-test",
                    step_name="nonexistent_step",
                    status=SagaStepStatus.COMPLETED,
                    result={"data": "test"},
                )

    @pytest.mark.asyncio
    async def test_cleanup_with_specific_statuses(self, postgres_container):
        """Test cleanup with specific status list (line 363->366)"""
        connection_string = postgres_container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )

        async with PostgreSQLSagaStorage(connection_string) as storage:
            # Create saga with FAILED status
            await storage.save_saga_state(
                saga_id="pg-failed-cleanup",
                saga_name="FailedCleanup",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
                metadata={},
            )

            # Cleanup only FAILED status
            deleted = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC) + timedelta(seconds=1),
                statuses=[SagaStatus.FAILED],
            )

            assert deleted >= 1


# Use pytest-xdist_group to ensure all Redis tests run on same worker
@pytest.mark.xdist_group(name="redis")
class TestRedisStorage:
    """Tests for Redis storage with real Redis instance"""

    @pytest.mark.asyncio
    async def test_save_and_load_saga_state(self, redis_container):
        """Test saving and loading saga state"""
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
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            state = await storage.load_saga_state("nonexistent-redis")
            assert state is None

    @pytest.mark.asyncio
    async def test_delete_saga_state(self, redis_container):
        """Test deleting saga state"""
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
            # Redis TTL expiration happens in background, so we need to wait a bit longer
            await asyncio.sleep(2.5)

            # Verify it's expired
            state = await storage.load_saga_state("redis-ttl-test")
            assert state is None

    @pytest.mark.asyncio
    async def test_update_existing_saga(self, redis_container):
        """Test updating an existing saga state"""
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
            import asyncio

            await asyncio.sleep(1.5)

            # Cleanup sagas older than now
            from datetime import datetime

            deleted_count = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))

            # At least our test saga should be deleted
            assert deleted_count >= 1

            # Verify saga is gone
            state = await storage.load_saga_state("redis-cleanup-test")
            assert state is None

    @pytest.mark.asyncio
    async def test_health_check(self, redis_container):
        """Test health check functionality"""
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
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url=redis_url) as storage:
            import json
            from datetime import datetime, timedelta

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
        """Test listing sagas with both status and name filters (lines 189-196)"""
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
    async def test_update_step_state_not_found(self, redis_container):
        """Test updating step state when step doesn't exist (line 255)"""
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url, key_prefix="step-not-found:") as storage:
            # Create a saga with one step
            await storage.save_saga_state(
                saga_id="redis-step-not-found",
                saga_name="StepNotFoundTest",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "existing_step", "status": "pending", "result": None}],
                context={},
                metadata={},
            )

            # Try to update a non-existent step
            with pytest.raises(SagaStorageError, match="not found"):
                await storage.update_step_state(
                    saga_id="redis-step-not-found",
                    step_name="nonexistent_step",
                    status=SagaStepStatus.COMPLETED,
                    result={"data": "test"},
                )

    @pytest.mark.asyncio
    async def test_delete_nonexistent_saga(self, redis_container):
        """Test deleting a saga that doesn't exist (line 150)"""
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}"

        async with RedisSagaStorage(redis_url, key_prefix="delete-test:") as storage:
            result = await storage.delete_saga_state("nonexistent-redis-saga-xyz")
            assert result is False

    @pytest.mark.asyncio
    async def test_list_sagas_no_filter_pagination(self, redis_container):
        """Test listing all sagas without filters uses pattern matching (lines 198-203)"""
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
