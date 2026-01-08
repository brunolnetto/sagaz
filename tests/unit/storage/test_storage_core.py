"""
Tests for sagaz.storage.core module.
"""

import json
from datetime import UTC, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from sagaz.storage.core import (
    BaseStorage,
    CapacityError,
    ConcurrencyError,
    ConnectionConfig,
    ConnectionError,
    HealthCheckResult,
    HealthStatus,
    NotFoundError,
    PoolStatus,
    SerializationError,
    StorageError,
    StorageStatistics,
    TransactionError,
    TransferError,
    deserialize,
    serialize,
)


class TestStorageErrors:
    """Tests for storage error hierarchy."""

    def test_storage_error_base(self):
        """Test base StorageError."""
        error = StorageError("Something failed")
        assert str(error) == "Something failed"
        assert error.message == "Something failed"
        assert error.details == {}

    def test_storage_error_with_details(self):
        """Test StorageError with details."""
        error = StorageError("Failed", details={"key": "value"})
        assert "key" in str(error)
        assert error.details == {"key": "value"}

    def test_connection_error(self):
        """Test ConnectionError with URL masking."""
        error = ConnectionError(
            message="Connection failed",
            backend="postgresql",
            url="postgresql://user:secret@localhost/db",
        )
        assert error.backend == "postgresql"
        # Password should be masked
        assert "secret" not in str(error)
        assert "***" in str(error)

    def test_not_found_error(self):
        """Test NotFoundError."""
        error = NotFoundError(
            message="Saga not found",
            item_type="saga",
            item_id="abc-123",
        )
        assert error.item_type == "saga"
        assert error.item_id == "abc-123"

    def test_serialization_error(self):
        """Test SerializationError."""
        error = SerializationError(
            message="JSON decode failed",
            operation="deserialize",
            data_type="dict",
        )
        assert error.operation == "deserialize"
        assert error.data_type == "dict"

    def test_transfer_error(self):
        """Test TransferError."""
        error = TransferError(
            message="Transfer interrupted",
            source="postgresql",
            target="redis",
            records_transferred=100,
            records_failed=5,
        )
        assert error.source == "postgresql"
        assert error.target == "redis"
        assert error.records_transferred == 100
        assert error.records_failed == 5

    def test_transaction_error(self):
        """Test TransactionError."""
        error = TransactionError(
            message="Commit failed",
            operation="commit",
        )
        assert error.operation == "commit"

    def test_concurrency_error(self):
        """Test ConcurrencyError."""
        error = ConcurrencyError(
            message="Version mismatch",
            item_id="saga-1",
            expected_version=1,
            actual_version=2,
        )
        assert error.expected_version == 1
        assert error.actual_version == 2

    def test_capacity_error(self):
        """Test CapacityError."""
        error = CapacityError(
            message="Memory limit reached",
            limit=1000,
            current=1500,
        )
        assert error.limit == 1000
        assert error.current == 1500

    def test_error_inheritance(self):
        """Test that all errors inherit from StorageError."""
        errors = [
            ConnectionError(),
            NotFoundError(),
            SerializationError(),
            TransferError(),
            TransactionError(),
            ConcurrencyError(),
            CapacityError(),
        ]
        for error in errors:
            assert isinstance(error, StorageError)
            assert isinstance(error, Exception)


class TestSerialization:
    """Tests for serialization utilities."""

    def test_serialize_simple_dict(self):
        """Test serializing a simple dictionary."""
        data = {"key": "value", "number": 42}
        result = serialize(data)
        assert isinstance(result, str)
        assert json.loads(result) == data

    def test_serialize_datetime(self):
        """Test datetime serialization."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        data = {"timestamp": dt}
        result = serialize(data)

        # Deserialize and verify
        parsed = deserialize(result)
        assert parsed["timestamp"] == dt

    def test_serialize_uuid(self):
        """Test UUID serialization."""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        data = {"id": uid}
        result = serialize(data)

        parsed = deserialize(result)
        assert parsed["id"] == uid

    def test_serialize_decimal(self):
        """Test Decimal serialization."""
        data = {"amount": Decimal("123.45")}
        result = serialize(data)

        parsed = deserialize(result)
        assert parsed["amount"] == Decimal("123.45")

    def test_serialize_bytes(self):
        """Test bytes serialization."""
        data = {"binary": b"hello world"}
        result = serialize(data)

        parsed = deserialize(result)
        assert parsed["binary"] == b"hello world"

    def test_serialize_set(self):
        """Test set serialization."""
        data = {"tags": {1, 2, 3}}
        result = serialize(data)

        parsed = deserialize(result)
        assert parsed["tags"] == {1, 2, 3}

    def test_serialize_nested(self):
        """Test nested structure serialization."""
        dt = datetime(2024, 1, 15, tzinfo=UTC)
        data = {
            "outer": {
                "inner": {
                    "timestamp": dt,
                    "id": UUID("12345678-1234-5678-1234-567812345678"),
                }
            }
        }
        result = serialize(data)
        parsed = deserialize(result)

        assert parsed["outer"]["inner"]["timestamp"] == dt

    def test_deserialize_invalid_json(self):
        """Test deserializing invalid JSON raises SerializationError."""
        with pytest.raises(SerializationError) as exc_info:
            deserialize("not valid json")

        assert exc_info.value.operation == "deserialize"

    def test_serialize_bytes_input(self):
        """Test deserializing bytes input."""
        data = {"key": "value"}
        serialized = serialize(data).encode("utf-8")

        parsed = deserialize(serialized)
        assert parsed == data


class TestHealthCheck:
    """Tests for health check infrastructure."""

    def test_health_status_values(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_health_check_result(self):
        """Test HealthCheckResult creation."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            latency_ms=5.5,
            message="All good",
        )
        assert result.is_healthy is True
        assert result.latency_ms == 5.5

    def test_health_check_result_degraded_is_healthy(self):
        """Test that DEGRADED is still considered healthy."""
        result = HealthCheckResult(
            status=HealthStatus.DEGRADED,
            latency_ms=100,
            message="High latency",
        )
        assert result.is_healthy is True

    def test_health_check_result_unhealthy(self):
        """Test unhealthy status."""
        result = HealthCheckResult(
            status=HealthStatus.UNHEALTHY,
            latency_ms=0,
            message="Connection failed",
        )
        assert result.is_healthy is False

    def test_health_check_result_to_dict(self):
        """Test HealthCheckResult.to_dict()."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            latency_ms=5.123,
            message="OK",
            details={"connections": 5},
        )
        data = result.to_dict()

        assert data["status"] == "healthy"
        assert data["is_healthy"] is True
        assert data["latency_ms"] == 5.12  # Rounded
        assert data["details"]["connections"] == 5

    def test_storage_statistics(self):
        """Test StorageStatistics."""
        stats = StorageStatistics(
            total_records=1000,
            pending_records=50,
            completed_records=900,
            failed_records=50,
        )
        assert stats.total_records == 1000

        data = stats.to_dict()
        assert data["pending_records"] == 50


class TestConnectionConfig:
    """Tests for ConnectionConfig."""

    def test_connection_config_defaults(self):
        """Test ConnectionConfig default values."""
        config = ConnectionConfig(url="redis://localhost")

        assert config.url == "redis://localhost"
        assert config.min_size == 1
        assert config.max_size == 10
        assert config.timeout_seconds == 30.0
        assert config.retry_attempts == 3
        assert config.options == {}

    def test_connection_config_custom(self):
        """Test ConnectionConfig with custom values."""
        config = ConnectionConfig(
            url="postgresql://localhost/db",
            min_size=5,
            max_size=20,
            timeout_seconds=60.0,
            options={"ssl": True},
        )

        assert config.min_size == 5
        assert config.max_size == 20
        assert config.options["ssl"] is True


class TestPoolStatus:
    """Tests for PoolStatus."""

    def test_pool_status_utilization(self):
        """Test pool utilization calculation."""
        status = PoolStatus(
            size=10,
            min_size=2,
            max_size=20,
            free=6,
            used=4,
        )
        assert status.utilization == 40.0

    def test_pool_status_empty(self):
        """Test pool utilization when empty."""
        status = PoolStatus(
            size=0,
            min_size=0,
            max_size=10,
            free=0,
            used=0,
        )
        assert status.utilization == 0.0
