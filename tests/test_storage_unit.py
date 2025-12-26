"""
Unit tests for storage backends without requiring Docker infrastructure.
These tests use mocking to verify the storage logic without actual database connections.
"""

from unittest.mock import AsyncMock, patch

import pytest

from sagaz.storage.base import SagaStorageConnectionError


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


class TestPostgreSQLSagaStorageUnit:
    """Unit tests for PostgreSQLSagaStorage without actual PostgreSQL"""

    @pytest.mark.asyncio
    async def test_postgresql_initialization(self):
        """Test PostgreSQL storage initialization"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.postgresql.asyncpg"):
                from sagaz.storage.postgresql import PostgreSQLSagaStorage

                storage = PostgreSQLSagaStorage(connection_string="postgresql://localhost/test")

                assert storage.connection_string == "postgresql://localhost/test"

    @pytest.mark.asyncio
    async def test_postgresql_connection_error_handling(self):
        """Test PostgreSQL connection error handling"""
        with patch("sagaz.storage.postgresql.ASYNCPG_AVAILABLE", True):
            with patch("sagaz.storage.postgresql.asyncpg") as mock_asyncpg:
                mock_asyncpg.create_pool = AsyncMock(side_effect=Exception("Connection refused"))

                from sagaz.storage.postgresql import PostgreSQLSagaStorage

                storage = PostgreSQLSagaStorage(connection_string="postgresql://invalid:9999/test")

                with pytest.raises(
                    SagaStorageConnectionError, match="Failed to connect to PostgreSQL"
                ):
                    await storage._get_pool()
