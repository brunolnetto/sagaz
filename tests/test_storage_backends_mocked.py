"""
Comprehensive tests for storage backends (PostgreSQL and Redis) with mocks.

These tests mock the database/redis connections to test the storage logic
without requiring actual database connections.
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, UTC, timedelta


class AsyncContextManagerMock:
    """Helper class to create async context manager mocks."""
    def __init__(self, return_value=None):
        self.return_value = return_value
        
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


# ============================================
# POSTGRESQL STORAGE MOCKED TESTS
# ============================================

class TestPostgreSQLSagaStorageMocked:
    """Test PostgreSQLSagaStorage with mocked asyncpg."""
    
    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        
        # Make execute, executemany, fetch, fetchrow, fetchval all async
        conn.execute = AsyncMock(return_value="OK")
        conn.executemany = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=1)
        
        # Setup async context manager for acquire
        pool.acquire.return_value = AsyncContextManagerMock(conn)
        
        # transaction() returns an async context manager (NOT a coroutine)
        conn.transaction.return_value = AsyncContextManagerMock(None)
        
        # Setup pool close as async
        pool.close = AsyncMock()
        pool.get_size = MagicMock(return_value=5)
        
        return pool, conn
    
    @pytest.mark.asyncio
    async def test_save_saga_state(self, mock_pool):
        """Test saving saga state."""
        from sagaz.types import SagaStatus
        
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            
            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="OrderSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={"order_id": "123"},
                metadata={"version": 1}
            )
            
            # Verify execute was called for saga upsert
            assert conn.execute.called
    
    @pytest.mark.asyncio
    async def test_load_saga_state(self, mock_pool):
        """Test loading saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            
            # Mock saga row
            saga_row = {
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "executing",
                "context": '{"order_id": "123"}',
                "metadata": '{}',
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            conn.fetchrow.return_value = saga_row
            
            # Mock step rows
            step_row = MagicMock()
            step_row.__getitem__ = lambda self, k: {
                "step_name": "step1",
                "status": "completed",
                "result": '{"data": "test"}',
                "error": None,
                "executed_at": datetime.now(UTC),
                "compensated_at": None,
                "retry_count": 0,
            }[k]
            conn.fetch.return_value = [step_row]
            
            result = await storage.load_saga_state("saga-123")
            
            assert result["saga_id"] == "saga-123"
            assert result["saga_name"] == "OrderSaga"
    
    @pytest.mark.asyncio
    async def test_load_saga_state_not_found(self, mock_pool):
        """Test loading non-existent saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.fetchrow.return_value = None
            
            result = await storage.load_saga_state("nonexistent")
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_delete_saga_state(self, mock_pool):
        """Test deleting saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "DELETE 1"
            
            result = await storage.delete_saga_state("saga-123")
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_delete_saga_state_not_found(self, mock_pool):
        """Test deleting non-existent saga state."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "DELETE 0"
            
            result = await storage.delete_saga_state("nonexistent")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_list_sagas(self, mock_pool):
        """Test listing sagas."""
        from sagaz.types import SagaStatus
        
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            
            # Mock row result
            row = {
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "completed",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "step_count": 3,
                "completed_steps": 3,
            }
            conn.fetch.return_value = [row]
            
            result = await storage.list_sagas(
                status=SagaStatus.COMPLETED,
                saga_name="Order",
                limit=10,
                offset=0
            )
            
            assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_update_step_state(self, mock_pool):
        """Test updating step state."""
        from sagaz.types import SagaStepStatus
        
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "UPDATE 1"
            
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"success": True},
                executed_at=datetime.now(UTC)
            )
            
            assert conn.execute.called
    
    @pytest.mark.asyncio
    async def test_update_step_state_not_found(self, mock_pool):
        """Test updating non-existent step raises error."""
        from sagaz.types import SagaStepStatus
        from sagaz.storage.base import SagaStorageError
        
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "UPDATE 0"
            
            with pytest.raises(SagaStorageError):
                await storage.update_step_state(
                    saga_id="saga-123",
                    step_name="nonexistent",
                    status=SagaStepStatus.COMPLETED
                )
    
    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, mock_pool):
        """Test getting saga statistics."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            
            conn.fetch.return_value = [
                {"status": "completed", "count": 100},
                {"status": "failed", "count": 5},
            ]
            conn.fetchrow.return_value = {"size": 1024000}
            
            stats = await storage.get_saga_statistics()
            
            assert stats["total_sagas"] == 105
            assert stats["by_status"]["completed"] == 100
    
    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, mock_pool):
        """Test cleaning up completed sagas."""
        from sagaz.types import SagaStatus
        
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.execute.return_value = "DELETE 50"
            
            count = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC) - timedelta(days=30)
            )
            
            assert count == 50
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_pool):
        """Test health check when healthy."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.fetchval.side_effect = [1, "PostgreSQL 15.0"]
            pool.get_size.return_value = 5
            
            result = await storage.health_check()
            
            assert result["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, mock_pool):
        """Test health check when unhealthy."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            pool, conn = mock_pool
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            storage._pool = pool
            conn.fetchval.side_effect = Exception("Connection lost")
            
            result = await storage.health_check()
            
            assert result["status"] == "unhealthy"
    
    def test_format_bytes(self):
        """Test bytes formatting helper."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            storage = PostgreSQLSagaStorage("postgresql://localhost/test")
            
            assert storage._format_bytes(500) == "500.0B"
            assert storage._format_bytes(1024) == "1.0KB"
            assert storage._format_bytes(1024 * 1024) == "1.0MB"
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True), \
             patch("sagaz.storage.postgresql.asyncpg") as mock_asyncpg:
            from sagaz.storage.postgresql import PostgreSQLSagaStorage
            
            # Create proper mocks
            mock_pool = MagicMock()
            mock_pool.close = AsyncMock()
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value = AsyncContextManagerMock(mock_conn)
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            
            async with PostgreSQLSagaStorage("postgresql://localhost/test") as storage:
                assert storage._pool is not None
            
            mock_pool.close.assert_called_once()


# ============================================
# REDIS STORAGE MOCKED TESTS
# ============================================

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
        from sagaz.types import SagaStatus
        
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
                context={"order_id": "123"}
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
        from sagaz.storage.base import SagaStorageError
        
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
            saga_data = json.dumps({
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "completed",
                "steps": [],
                "context": {},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
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
        from sagaz.types import SagaStatus
        
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            
            # Mock status index
            client.smembers.return_value = {b"saga-123"}
            
            # Mock saga data
            saga_data = json.dumps({
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "completed",
                "steps": [],
                "context": {},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            client.hget.return_value = saga_data.encode()
            
            result = await storage.list_sagas(status=SagaStatus.COMPLETED)
            
            assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_update_step_state(self, mock_redis):
        """Test updating step state."""
        from sagaz.types import SagaStatus, SagaStepStatus
        
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            
            saga_data = json.dumps({
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "executing",
                "steps": [{"name": "step1", "status": "pending"}],
                "context": {},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            client.hget.return_value = saga_data.encode()
            
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"success": True}
            )
    
    @pytest.mark.asyncio
    async def test_update_step_state_saga_not_found(self, mock_redis):
        """Test updating step when saga not found."""
        from sagaz.types import SagaStepStatus
        from sagaz.storage.base import SagaNotFoundError
        
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            client.hget.return_value = None
            
            with pytest.raises(SagaNotFoundError):
                await storage.update_step_state(
                    saga_id="nonexistent",
                    step_name="step1",
                    status=SagaStepStatus.COMPLETED
                )
    
    @pytest.mark.asyncio
    async def test_update_step_state_step_not_found(self, mock_redis):
        """Test updating non-existent step raises error."""
        from sagaz.types import SagaStepStatus
        from sagaz.storage.base import SagaStorageError
        
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            
            saga_data = json.dumps({
                "saga_id": "saga-123",
                "saga_name": "OrderSaga",
                "status": "executing",
                "steps": [{"name": "step1", "status": "pending"}],
                "context": {},
                "metadata": {},
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
            client.hget.return_value = saga_data.encode()
            
            with pytest.raises(SagaStorageError):
                await storage.update_step_state(
                    saga_id="saga-123",
                    step_name="nonexistent_step",
                    status=SagaStepStatus.COMPLETED
                )
    
    @pytest.mark.asyncio
    async def test_get_saga_statistics(self, mock_redis):
        """Test getting saga statistics."""
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            
            client.info.return_value = {
                "used_memory": 1024000,
                "used_memory_human": "1M"
            }
            client.scard.return_value = 10
            
            stats = await storage.get_saga_statistics()
            
            assert "total_sagas" in stats
            assert "redis_memory_human" in stats
    
    @pytest.mark.asyncio
    async def test_cleanup_completed_sagas(self, mock_redis):
        """Test cleaning up old completed sagas."""
        from sagaz.types import SagaStatus
        
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            client, pipeline = mock_redis
            storage = RedisSagaStorage("redis://localhost:6379")
            storage._redis = client
            
            # Mock saga IDs in status index
            client.smembers.return_value = {b"saga-old"}
            
            # Mock old saga data
            old_saga = json.dumps({
                "saga_id": "saga-old",
                "saga_name": "OldSaga",
                "status": "completed",
                "steps": [],
                "context": {},
                "metadata": {},
                "created_at": "2023-01-01T00:00:00+00:00",
                "updated_at": "2023-01-01T00:00:00+00:00",
            })
            client.hget.return_value = old_saga.encode()
            pipeline.execute.return_value = [1]
            
            count = await storage.cleanup_completed_sagas(
                older_than=datetime.now(UTC)
            )
            
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
                "used_memory_human": "1M"
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
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True), \
             patch("sagaz.storage.redis.redis") as mock_redis_module:
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
        with patch("sagaz.storage.redis.REDIS_AVAILABLE", True):
            from sagaz.storage.redis import RedisSagaStorage
            
            storage = RedisSagaStorage("redis://localhost:6379", key_prefix="test:")
            
            assert storage._saga_key("123") == "test:123"
            assert storage._step_key("123", "step1") == "test:123:step:step1"
            assert storage._index_key("status") == "test:index:status"
