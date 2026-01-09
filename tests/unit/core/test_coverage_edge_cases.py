"""
Tests for coverage edge cases.

These tests cover specific edge cases that were previously missing coverage:
- Serialization edge cases (enum handling, type fallbacks)
- Connection manager edge cases (re-initialization, validation)
- Transfer service edge cases (retry success, skip on error)
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# ============================================
# SERIALIZATION EDGE CASES
# ============================================


class TestSerializationEdgeCases:
    """Tests for serialization edge cases."""

    def test_storage_decoder_enum_type(self):
        """Test that enum-typed values are decoded correctly."""
        from sagaz.storage.core.serialization import storage_decoder

        # Enum values are stored with __type__: enum
        obj = {"__type__": "enum", "value": "completed"}
        result = storage_decoder(obj)

        # Should return the value as-is (can't restore enum class)
        assert result == "completed"

    def test_storage_decoder_unknown_type(self):
        """Test that unknown types return the original object."""
        from sagaz.storage.core.serialization import storage_decoder

        # Unknown type should return the object as-is
        obj = {"__type__": "unknown_type", "value": "data"}
        result = storage_decoder(obj)

        assert result == obj

    def test_storage_decoder_no_type_key(self):
        """Test that objects without __type__ are returned as-is."""
        from sagaz.storage.core.serialization import storage_decoder

        obj = {"key": "value", "nested": {"data": 123}}
        result = storage_decoder(obj)

        assert result == obj

    def test_storage_encoder_with_dict_object(self):
        """Test that objects with __dict__ are serialized."""
        import json

        from sagaz.storage.core.serialization import StorageEncoder

        class CustomObject:
            def __init__(self):
                self.name = "test"
                self.value = 42

        obj = CustomObject()
        StorageEncoder()

        # Should serialize using __dict__
        result = json.dumps(obj, cls=StorageEncoder)
        parsed = json.loads(result)

        assert parsed["name"] == "test"
        assert parsed["value"] == 42


# ============================================
# CONNECTION MANAGER EDGE CASES
# ============================================


class TestConnectionManagerEdgeCases:
    """Tests for connection manager edge cases."""

    @pytest.mark.asyncio
    async def test_initialize_already_initialized(self):
        """Test that initialize returns early if already initialized."""
        from sagaz.storage.core.connection import ConnectionConfig, SingleConnectionManager

        # Create a concrete implementation for testing
        class TestConnectionManager(SingleConnectionManager[MagicMock]):
            async def _create_connection(self):
                return MagicMock()

            async def _close_connection(self, connection):
                pass

            async def _is_connection_valid(self, connection):
                return True

        manager = TestConnectionManager(ConnectionConfig(url="test://localhost"))

        # First initialization
        await manager.initialize()
        assert manager._initialized is True

        # Second initialization should return early
        await manager.initialize()
        assert manager._initialized is True

        await manager.close()

    @pytest.mark.asyncio
    async def test_acquire_without_connection(self):
        """Test that _acquire initializes if no connection exists."""
        from sagaz.storage.core.connection import ConnectionConfig, SingleConnectionManager

        class TestConnectionManager(SingleConnectionManager[MagicMock]):
            def __init__(self, config):
                super().__init__(config)
                self.init_count = 0

            async def _create_connection(self):
                self.init_count += 1
                return MagicMock()

            async def _close_connection(self, connection):
                pass

            async def _is_connection_valid(self, connection):
                return True

        manager = TestConnectionManager(ConnectionConfig(url="test://localhost"))

        # Connection is None initially
        assert manager._connection is None

        # _acquire should initialize
        conn = await manager._acquire()

        assert conn is not None
        assert manager.init_count == 1
        assert manager._initialized is True

        await manager.close()

    @pytest.mark.asyncio
    async def test_acquire_with_invalid_connection(self):
        """Test that _acquire re-initializes if connection is invalid."""
        from sagaz.storage.core.connection import ConnectionConfig, SingleConnectionManager

        class TestConnectionManager(SingleConnectionManager[MagicMock]):
            def __init__(self, config):
                super().__init__(config)
                self.init_count = 0
                self.is_valid = True

            async def _create_connection(self):
                self.init_count += 1
                return MagicMock()

            async def _close_connection(self, connection):
                pass

            async def _is_connection_valid(self, connection):
                return self.is_valid

        manager = TestConnectionManager(ConnectionConfig(url="test://localhost"))

        # First acquisition
        await manager.initialize()
        assert manager.init_count == 1

        # Simulate connection becoming invalid
        manager.is_valid = False

        # _acquire should detect invalid and re-initialize
        await manager._acquire()

        assert manager.init_count == 2  # Re-initialized

        await manager.close()

    @pytest.mark.asyncio
    async def test_health_check_valid_connection(self):
        """Test health check with valid connection."""
        from sagaz.storage.core.connection import ConnectionConfig, SingleConnectionManager
        from sagaz.storage.core.health import HealthStatus

        class TestConnectionManager(SingleConnectionManager[MagicMock]):
            async def _create_connection(self):
                return MagicMock()

            async def _close_connection(self, connection):
                pass

            async def _is_connection_valid(self, connection):
                return True

        manager = TestConnectionManager(ConnectionConfig(url="test://localhost"))
        await manager.initialize()

        result = await manager.health_check()

        assert result.status == HealthStatus.HEALTHY
        assert result.latency_ms > 0

        await manager.close()


# ============================================
# TRANSFER SERVICE EDGE CASES
# ============================================


class TestTransferServiceEdgeCases:
    """Tests for transfer service edge cases."""

    @pytest.mark.asyncio
    async def test_transfer_with_skip_on_error(self):
        """Test transfer that skips failed records."""
        from sagaz.storage.transfer.service import (
            TransferConfig,
            TransferErrorPolicy,
            TransferService,
        )

        # Mock source that yields some records, one will fail
        mock_source = AsyncMock()

        async def mock_export():
            yield {"saga_id": "good-1", "data": "ok"}
            yield {"saga_id": "bad-1", "data": "will_fail"}
            yield {"saga_id": "good-2", "data": "ok"}

        mock_source.export_all = mock_export
        mock_source.count = AsyncMock(return_value=3)

        # Mock target that fails on specific record
        mock_target = AsyncMock()

        async def mock_import(record):
            if record["saga_id"] == "bad-1":
                msg = "Import failed"
                raise ValueError(msg)

        mock_target.import_record = mock_import

        config = TransferConfig(
            on_error=TransferErrorPolicy.SKIP,
            batch_size=10,
        )

        service = TransferService(mock_source, mock_target, config)

        result = await service.transfer_all()

        # Should have 2 transferred, 1 skipped
        assert result.transferred == 2
        assert result.skipped == 1
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_transfer_with_retry_success(self):
        """Test transfer that retries and succeeds."""
        from sagaz.storage.transfer.service import (
            TransferConfig,
            TransferErrorPolicy,
            TransferService,
        )

        # Mock source
        mock_source = AsyncMock()

        async def mock_export():
            yield {"saga_id": "retry-1", "data": "will_retry"}

        mock_source.export_all = mock_export
        mock_source.count = AsyncMock(return_value=1)

        # Mock target that fails first time, succeeds on retry
        mock_target = AsyncMock()
        call_count = 0

        async def mock_import(record):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "First attempt fails"
                raise ValueError(msg)
            # Second attempt succeeds

        mock_target.import_record = mock_import

        config = TransferConfig(
            on_error=TransferErrorPolicy.RETRY,
            max_retries=3,
            retry_delay_seconds=0.01,  # Fast for testing
            batch_size=10,
        )

        service = TransferService(mock_source, mock_target, config)

        result = await service.transfer_all()

        # Should have succeeded on retry
        assert result.transferred == 1
        assert result.failed == 0


# ============================================
# STORAGE MANAGER EDGE CASES
# ============================================


class TestStorageManagerEdgeCases:
    """Tests for storage manager edge cases."""

    def test_normalize_health_result_with_to_dict(self):
        """Test normalizing health result with to_dict method."""
        from sagaz.storage.manager import StorageManager

        class MockResult:
            def to_dict(self):
                return {"status": "healthy", "latency_ms": 10}

        result = StorageManager._normalize_health_result(MockResult())

        assert result == {"status": "healthy", "latency_ms": 10}

    def test_normalize_health_result_with_status_attr(self):
        """Test normalizing health result with status attribute."""
        from sagaz.storage.core.health import HealthStatus
        from sagaz.storage.manager import StorageManager

        class MockResult:
            def __init__(self):
                self.status = HealthStatus.HEALTHY

        result = StorageManager._normalize_health_result(MockResult())

        assert result == {"status": "healthy"}

    def test_normalize_health_result_with_dict(self):
        """Test normalizing health result that is already a dict."""
        from sagaz.storage.manager import StorageManager

        result = StorageManager._normalize_health_result({"status": "healthy"})

        assert result == {"status": "healthy"}

    def test_normalize_health_result_fallback(self):
        """Test normalizing health result with unknown type."""
        from sagaz.storage.manager import StorageManager

        # Pass something that's not a dict and has no to_dict or status
        result = StorageManager._normalize_health_result("unknown")

        assert result == {"status": "healthy"}
