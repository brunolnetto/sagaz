"""
Tests for worker main() CLI entry point and storage backend edge cases.

Covers:
- Worker main() function with mocked dependencies
- PostgreSQL storage edge cases (JSON parsing, timestamp handling)
- Redis storage edge cases (filtering, error paths)
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class AsyncContextManagerMock:
    """Helper class to create async context manager mocks."""

    def __init__(self, return_value=None):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


# ============================================
# WORKER MAIN() CLI TESTS
# ============================================


class TestWorkerMain:
    """Test the worker main() entry point."""

    @pytest.mark.asyncio
    async def test_main_starts_and_stops_worker(self):
        """Test that main() starts the worker and handles shutdown."""
        from sagaz.outbox.worker import main

        # Mock the storage and broker
        mock_storage = AsyncMock()
        mock_storage.initialize = AsyncMock()
        mock_storage.close = AsyncMock()

        mock_broker = AsyncMock()
        mock_broker.connect = AsyncMock()
        mock_broker.close = AsyncMock()

        # Mock OutboxWorker
        mock_worker = AsyncMock()
        mock_worker.worker_id = "test-worker-1"
        mock_worker.start = AsyncMock(side_effect=KeyboardInterrupt())  # Simulate Ctrl+C
        mock_worker.stop = AsyncMock()

        with (
            patch("sagaz.outbox.worker.get_storage", return_value=mock_storage),
            patch("sagaz.outbox.worker.get_broker", return_value=mock_broker),
            patch("sagaz.outbox.worker.OutboxWorker", return_value=mock_worker),
        ):
            # Run main - should handle KeyboardInterrupt
            await main()

            # Verify lifecycle
            mock_storage.initialize.assert_called_once()
            mock_broker.connect.assert_called_once()
            mock_worker.start.assert_called_once()
            mock_worker.stop.assert_called_once()
            mock_broker.close.assert_called_once()
            mock_storage.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_handles_startup_error(self):
        """Test that main() handles errors during startup."""
        from sagaz.outbox.worker import main

        mock_storage = AsyncMock()
        mock_storage.initialize = AsyncMock(side_effect=Exception("DB connection failed"))
        mock_storage.close = AsyncMock()

        mock_broker = AsyncMock()
        mock_broker.connect = AsyncMock()
        mock_broker.close = AsyncMock()

        mock_worker = AsyncMock()
        mock_worker.worker_id = "test-worker"
        mock_worker.stop = AsyncMock()

        with (
            patch("sagaz.outbox.worker.get_storage", return_value=mock_storage),
            patch("sagaz.outbox.worker.get_broker", return_value=mock_broker),
            patch("sagaz.outbox.worker.OutboxWorker", return_value=mock_worker),
        ):
            # Should raise the exception (no catch in main)
            with pytest.raises(Exception, match="DB connection failed"):
                await main()


# ============================================
# POSTGRESQL STORAGE EDGE CASES
# ============================================


class TestPostgreSQLStorageEdgeCases:
    """Test edge cases in PostgreSQL storage."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()

        # Make specific methods async
        conn.execute = AsyncMock(return_value="OK")
        conn.executemany = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=1)

        # Setup async context managers
        pool.acquire.return_value = AsyncContextManagerMock(conn)
        conn.transaction.return_value = AsyncContextManagerMock(None)
        pool.close = AsyncMock()
        pool.get_size = MagicMock(return_value=5)

        return pool, conn

    @pytest.mark.asyncio
    async def test_load_saga_with_invalid_json_result(self, mock_pool):
        """Test loading saga when step result is not valid JSON (fallback to raw)."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            # Mock saga row
            saga_row = {
                "saga_id": "saga-123",
                "saga_name": "TestSaga",
                "status": "completed",
                "context": '{"key": "value"}',
                "metadata": "{}",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            conn.fetchrow.return_value = saga_row

            # Mock step with INVALID JSON result (line 204-205 coverage)
            step_row = {
                "step_name": "step1",
                "status": "completed",
                "result": "not-valid-json{",  # Invalid JSON
                "error": None,
                "executed_at": datetime.now(UTC),
                "compensated_at": datetime.now(UTC),  # Also covers line 211
                "retry_count": 0,
            }
            conn.fetch.return_value = [step_row]

            result = await storage.load_saga_state("saga-123")

            # Result should fall back to raw string
            assert result["steps"][0]["result"] == "not-valid-json{"
            # compensated_at should be present
            assert result["steps"][0]["compensated_at"] is not None

    @pytest.mark.asyncio
    async def test_load_saga_with_no_executed_at(self, mock_pool):
        """Test loading saga when step has no executed_at timestamp."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            saga_row = {
                "saga_id": "saga-123",
                "saga_name": "TestSaga",
                "status": "pending",
                "context": "{}",
                "metadata": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            conn.fetchrow.return_value = saga_row

            # Step with NO timestamps (covers branches 208->210, etc.)
            step_row = {
                "step_name": "step1",
                "status": "pending",
                "result": None,
                "error": None,
                "executed_at": None,
                "compensated_at": None,
                "retry_count": 0,
            }
            conn.fetch.return_value = [step_row]

            result = await storage.load_saga_state("saga-123")

            # Should have no executed_at in step
            assert (
                "executed_at" not in result["steps"][0]
                or result["steps"][0].get("executed_at") is None
            )

    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas_parses_count(self, mock_pool):
        """Test cleanup extracts count from DELETE result."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            # Test with various DELETE results (covers line 396)
            conn.execute.return_value = "DELETE 42"
            count = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))
            assert count == 42

            conn.execute.return_value = "DELETE 0"
            count = await storage.cleanup_completed_sagas(older_than=datetime.now(UTC))
            assert count == 0

    @pytest.mark.asyncio
    async def test_get_statistics_with_valid_size(self, mock_pool):
        """Test statistics with valid database size."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool

            conn.fetch.return_value = [
                {"status": "completed", "count": 10},
                {"status": "failed", "count": 2},
            ]
            conn.fetchrow.return_value = {"size": 1024000}

            stats = await storage.get_saga_statistics()

            assert stats["total_sagas"] == 12
            assert stats["database_size_bytes"] == 1024000


# ============================================
# REDIS STORAGE EDGE CASES
# ============================================


class TestRedisSagaStorageEdgeCases:
    """Test edge cases in Redis storage."""

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

        # Setup pipeline
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
    async def test_list_sagas_with_both_status_and_name_filters(self, mock_redis):
        """Test listing sagas with both status and name filters (intersection)."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            from sagaz.types import SagaStatus

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            # Status filter returns saga-1, saga-2
            # Name filter returns saga-2, saga-3
            # Intersection should be saga-2

            async def mock_smembers(key):
                if "status:completed" in key:
                    return {b"saga-1", b"saga-2"}
                if "name:OrderSaga" in key:
                    return {b"saga-2", b"saga-3"}
                return set()

            client.smembers.side_effect = mock_smembers

            # Mock saga data for saga-2
            saga_data = json.dumps(
                {
                    "saga_id": "saga-2",
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

            result = await storage.list_sagas(status=SagaStatus.COMPLETED, saga_name="OrderSaga")

            # Should only return saga-2 (intersection)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_sagas_no_filters_gets_all(self, mock_redis):
        """Test listing sagas without filters returns all sagas."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379", key_prefix="saga:")
            storage._redis = client

            # Mock keys (covers _get_all_saga_ids)
            client.keys.return_value = [
                b"saga:id-1",
                b"saga:id-2",
                b"saga:id-1:step:step1",  # Should be filtered out
                b"saga:index:status",  # Should be filtered out
            ]

            # Mock saga data
            saga_data = json.dumps(
                {
                    "saga_id": "id-1",
                    "saga_name": "TestSaga",
                    "status": "completed",
                    "steps": [],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()

            result = await storage.list_sagas(limit=10)

            # Should filter out :step: and :index: keys
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_update_step_with_executed_at_timestamp(self, mock_redis):
        """Test updating step with executed_at timestamp."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            from sagaz.types import SagaStepStatus

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            saga_data = json.dumps(
                {
                    "saga_id": "saga-123",
                    "saga_name": "TestSaga",
                    "status": "executing",
                    "steps": [{"name": "step1", "status": "pending"}],
                    "context": {},
                    "metadata": {},
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                }
            )
            client.hget.return_value = saga_data.encode()

            # Use executed_at which IS a valid parameter
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"success": True},
                executed_at=datetime.now(UTC),
            )

            # Verify hset was called (step update)
            assert client.hset.called or pipeline.hset.called

    @pytest.mark.asyncio
    async def test_health_check_with_ping_and_info(self, mock_redis):
        """Test health check gets server info."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage

            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client

            # Mock info response (covers health check info parsing)
            client.info.return_value = {
                "redis_version": "7.0.5",
                "connected_clients": 10,
                "used_memory_human": "2M",
            }

            result = await storage.health_check()

            assert result["status"] == "healthy"
            assert result["storage_type"] == "redis"
            assert "redis_version" in result
