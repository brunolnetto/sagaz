"""
Additional tests for sagaz.storage.core modules to improve coverage.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from sagaz.storage.core import (
    BaseStorage,
    ConnectionConfig,
    ConnectionManager,
    HealthCheckResult,
    HealthCheckable,
    HealthStatus,
    SingleConnectionManager,
    StorageStatistics,
    TransferableStorage,
    check_health_with_timeout,
    deserialize,
    deserialize_from_redis,
    serialize,
    serialize_for_redis,
)


class TestBaseStorageExtended:
    """Extended tests for BaseStorage class."""

    def test_base_storage_abstract(self):
        """Test that BaseStorage is abstract."""
        with pytest.raises(TypeError):
            BaseStorage()

    @pytest.mark.asyncio
    async def test_base_storage_context_manager(self):
        """Test context manager support."""
        class ConcreteStorage(BaseStorage):
            async def close(self):
                self._closed = True

        storage = ConcreteStorage()
        
        async with storage:
            assert not storage.is_closed
        
        assert storage.is_closed

    @pytest.mark.asyncio
    async def test_base_storage_health_check_closed(self):
        """Test health check returns unhealthy when closed."""
        class ConcreteStorage(BaseStorage):
            async def close(self):
                self._closed = True

        storage = ConcreteStorage()
        await storage.close()
        
        result = await storage.health_check()
        assert result.status == HealthStatus.UNHEALTHY
        assert "closed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_base_storage_health_check_with_connection_manager(self):
        """Test health check uses connection manager."""
        mock_manager = AsyncMock()
        mock_manager.health_check.return_value = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            latency_ms=5.0,
            message="OK",
        )
        
        class ConcreteStorage(BaseStorage):
            async def close(self):
                pass

        storage = ConcreteStorage(connection_manager=mock_manager)
        result = await storage.health_check()
        
        assert result.status == HealthStatus.HEALTHY
        mock_manager.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_base_storage_get_statistics_default(self):
        """Test default statistics returns empty."""
        class ConcreteStorage(BaseStorage):
            async def close(self):
                pass

        storage = ConcreteStorage()
        stats = await storage.get_statistics()
        
        assert isinstance(stats, StorageStatistics)
        assert stats.total_records == 0

    def test_log_operation(self):
        """Test logging operation."""
        class ConcreteStorage(BaseStorage):
            async def close(self):
                pass

        storage = ConcreteStorage()
        # Should not raise
        storage._log_operation("test_operation", item_id="123", extra="data")


class TestTransferableStorageExtended:
    """Extended tests for TransferableStorage class."""

    @pytest.mark.asyncio
    async def test_clear_not_implemented(self):
        """Test clear raises NotImplementedError."""
        class ConcreteTransferable(TransferableStorage):
            async def close(self):
                pass
            
            async def export_all(self):
                yield {}
            
            async def import_record(self, record):
                pass
            
            async def count(self):
                return 0

        storage = ConcreteTransferable()
        
        with pytest.raises(NotImplementedError):
            await storage.clear()


class TestConnectionConfigExtended:
    """Extended tests for ConnectionConfig."""

    def test_connection_config_options_default(self):
        """Test options default to empty dict."""
        config = ConnectionConfig(url="redis://localhost")
        assert config.options == {}

    def test_connection_config_with_none_options(self):
        """Test options=None becomes empty dict."""
        config = ConnectionConfig(url="redis://localhost", options=None)
        assert config.options == {}


class TestSerializationExtended:
    """Extended tests for serialization utilities."""

    def test_serialize_enum(self):
        """Test enum serialization."""
        class Color(Enum):
            RED = "red"
            BLUE = "blue"
        
        data = {"color": Color.RED}
        result = serialize(data)
        
        # Should contain enum value
        assert "red" in result

    def test_serialize_frozenset(self):
        """Test frozenset serialization."""
        data = {"tags": frozenset([1, 2, 3])}
        result = serialize(data)
        parsed = deserialize(result)
        
        assert parsed["tags"] == frozenset([1, 2, 3])

    def test_serialize_object_with_dict(self):
        """Test object with __dict__ serialization."""
        class Simple:
            def __init__(self):
                self.name = "test"
                self.value = 42
        
        data = {"obj": Simple()}
        result = serialize(data)
        
        # Should serialize the __dict__
        assert "test" in result
        assert "42" in result

    def test_serialize_for_redis_none(self):
        """Test Redis serialization handles None."""
        data = {"key": None}
        result = serialize_for_redis(data)
        assert result["key"] == ""

    def test_serialize_for_redis_bool(self):
        """Test Redis serialization handles bool."""
        data = {"enabled": True, "disabled": False}
        result = serialize_for_redis(data)
        assert result["enabled"] == "true"
        assert result["disabled"] == "false"

    def test_serialize_for_redis_datetime(self):
        """Test Redis serialization handles datetime."""
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        data = {"timestamp": dt}
        result = serialize_for_redis(data)
        assert "2024-01-15" in result["timestamp"]

    def test_serialize_for_redis_uuid(self):
        """Test Redis serialization handles UUID."""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        data = {"id": uid}
        result = serialize_for_redis(data)
        assert result["id"] == "12345678-1234-5678-1234-567812345678"

    def test_serialize_for_redis_complex(self):
        """Test Redis serialization handles complex types."""
        data = {"nested": {"key": "value"}}
        result = serialize_for_redis(data)
        # Complex types get JSON encoded
        assert "{" in result["nested"]

    def test_deserialize_from_redis_bytes(self):
        """Test Redis deserialization handles bytes."""
        data = {b"key": b"value", b"num": b"42"}
        result = deserialize_from_redis(data)
        assert result["key"] == "value"
        assert result["num"] == "42"

    def test_deserialize_from_redis_with_schema(self):
        """Test Redis deserialization with type schema."""
        data = {"count": "42", "enabled": "true", "rate": "3.14"}
        schema = {"count": int, "enabled": bool, "rate": float}
        
        result = deserialize_from_redis(data, schema=schema)
        
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["rate"] == 3.14

    def test_deserialize_from_redis_datetime_schema(self):
        """Test Redis deserialization with datetime schema."""
        data = {"timestamp": "2024-01-15T10:30:00+00:00"}
        schema = {"timestamp": datetime}
        
        result = deserialize_from_redis(data, schema=schema)
        
        assert isinstance(result["timestamp"], datetime)

    def test_deserialize_from_redis_uuid_schema(self):
        """Test Redis deserialization with UUID schema."""
        data = {"id": "12345678-1234-5678-1234-567812345678"}
        schema = {"id": UUID}
        
        result = deserialize_from_redis(data, schema=schema)
        
        assert isinstance(result["id"], UUID)

    def test_deserialize_from_redis_json_value(self):
        """Test Redis deserialization of JSON values."""
        data = {"nested": '{"key": "value"}'}
        
        result = deserialize_from_redis(data)
        
        assert result["nested"] == {"key": "value"}

    def test_deserialize_from_redis_invalid_json(self):
        """Test Redis deserialization handles invalid JSON."""
        data = {"value": "{not valid json"}
        
        result = deserialize_from_redis(data)
        
        # Should return as string
        assert result["value"] == "{not valid json"

    def test_deserialize_from_redis_empty_string(self):
        """Test Redis deserialization handles empty string as None."""
        data = {"value": ""}
        
        result = deserialize_from_redis(data)
        
        assert result["value"] is None


class TestHealthCheckExtended:
    """Extended tests for health check utilities."""

    @pytest.mark.asyncio
    async def test_check_health_with_timeout_success(self):
        """Test health check with timeout succeeds."""
        class MockHealthCheckable(HealthCheckable):
            async def health_check(self):
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    latency_ms=5.0,
                    message="OK",
                )
            
            async def get_statistics(self):
                return StorageStatistics()

        checker = MockHealthCheckable()
        result = await check_health_with_timeout(checker, timeout_seconds=5.0)
        
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_health_with_timeout_timeout(self):
        """Test health check with timeout times out."""
        class SlowHealthCheckable(HealthCheckable):
            async def health_check(self):
                await asyncio.sleep(10)  # Very slow
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    latency_ms=0,
                )
            
            async def get_statistics(self):
                return StorageStatistics()

        checker = SlowHealthCheckable()
        result = await check_health_with_timeout(checker, timeout_seconds=0.1)
        
        assert result.status == HealthStatus.UNHEALTHY
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_health_with_timeout_exception(self):
        """Test health check with timeout handles exception."""
        class FailingHealthCheckable(HealthCheckable):
            async def health_check(self):
                raise Exception("Connection failed")
            
            async def get_statistics(self):
                return StorageStatistics()

        checker = FailingHealthCheckable()
        result = await check_health_with_timeout(checker, timeout_seconds=5.0)
        
        assert result.status == HealthStatus.UNHEALTHY
        assert "Connection failed" in result.message


class TestSingleConnectionManagerExtended:
    """Extended tests for SingleConnectionManager."""

    @pytest.mark.asyncio
    async def test_single_connection_manager_lifecycle(self):
        """Test single connection manager lifecycle."""
        mock_conn = MagicMock()
        
        class ConcreteSingle(SingleConnectionManager):
            async def _create_connection(self):
                return mock_conn
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return True

        config = ConnectionConfig(url="test://localhost")
        manager = ConcreteSingle(config)
        
        # Initialize
        await manager.initialize()
        assert manager._initialized is True
        
        # Acquire
        conn = await manager._acquire()
        assert conn == mock_conn
        
        # Release (no-op for single connection)
        await manager._release(conn)
        
        # Close
        await manager.close()
        assert manager._initialized is False

    @pytest.mark.asyncio
    async def test_single_connection_manager_reconnect(self):
        """Test reconnection when connection is invalid."""
        connection_count = [0]
        
        class ReconnectingSingle(SingleConnectionManager):
            async def _create_connection(self):
                connection_count[0] += 1
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                # First call returns False to trigger reconnect
                return connection_count[0] > 1

        config = ConnectionConfig(url="test://localhost")
        manager = ReconnectingSingle(config)
        
        await manager.initialize()
        
        # First acquire, connection invalid, should reconnect
        await manager._acquire()
        
        # Should have created 2 connections
        assert connection_count[0] == 2

    @pytest.mark.asyncio
    async def test_single_connection_manager_pool_status(self):
        """Test pool status for single connection."""
        class ConcreteSingle(SingleConnectionManager):
            async def _create_connection(self):
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return True

        config = ConnectionConfig(url="test://localhost")
        manager = ConcreteSingle(config)
        
        # Before init
        status = manager.get_pool_status()
        assert status.size == 0
        
        # After init
        await manager.initialize()
        status = manager.get_pool_status()
        assert status.size == 1
        assert status.free == 1

    @pytest.mark.asyncio
    async def test_single_connection_manager_health_check_no_connection(self):
        """Test health check with no connection."""
        class ConcreteSingle(SingleConnectionManager):
            async def _create_connection(self):
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return True

        config = ConnectionConfig(url="test://localhost")
        manager = ConcreteSingle(config)
        
        result = await manager.health_check()
        assert result.status == HealthStatus.UNHEALTHY
        assert "No connection" in result.message

    @pytest.mark.asyncio
    async def test_single_connection_manager_health_check_invalid(self):
        """Test health check when connection is invalid."""
        class InvalidSingle(SingleConnectionManager):
            async def _create_connection(self):
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return False

        config = ConnectionConfig(url="test://localhost")
        manager = InvalidSingle(config)
        await manager.initialize()
        
        result = await manager.health_check()
        assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_single_connection_manager_health_check_exception(self):
        """Test health check handles exception."""
        class FailingSingle(SingleConnectionManager):
            async def _create_connection(self):
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                raise Exception("Check failed")

        config = ConnectionConfig(url="test://localhost")
        manager = FailingSingle(config)
        await manager.initialize()
        
        result = await manager.health_check()
        assert result.status == HealthStatus.UNHEALTHY
        assert "Check failed" in result.message

    @pytest.mark.asyncio
    async def test_single_connection_manager_context_manager(self):
        """Test context manager usage."""
        class ConcreteSingle(SingleConnectionManager):
            async def _create_connection(self):
                return MagicMock()
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return True

        config = ConnectionConfig(url="test://localhost")
        
        async with ConcreteSingle(config) as manager:
            assert manager._initialized

    @pytest.mark.asyncio
    async def test_connection_manager_acquire_context_manager(self):
        """Test acquire as context manager."""
        class ConcreteSingle(SingleConnectionManager):
            async def _create_connection(self):
                return "test_connection"
            
            async def _close_connection(self, conn):
                pass
            
            async def _is_connection_valid(self, conn):
                return True

        config = ConnectionConfig(url="test://localhost")
        manager = ConcreteSingle(config)
        
        async with manager.acquire() as conn:
            assert conn == "test_connection"
