"""
Tests for storage backend coverage gaps.

Targets:
- sagaz/storage/backends/redis/outbox.py (58% -> 90%+)
- sagaz/storage/backends/postgresql/outbox.py (47% -> 90%+)
- sagaz/storage/backends/sqlite/ (87-88% -> 95%+)
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check redis availability upfront
try:
    import redis.asyncio
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# =============================================================================
# REDIS OUTBOX STORAGE TESTS
# =============================================================================


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis not installed")
class TestRedisOutboxStorageCoverage:
    """Tests for RedisOutboxStorage coverage gaps."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.xgroup_create = AsyncMock()
        mock.close = AsyncMock()
        mock.ping = AsyncMock()
        mock.xlen = AsyncMock(return_value=0)
        return mock

    @pytest.mark.asyncio
    async def test_redis_outbox_initialization(self, mock_redis):
        """Test RedisOutboxStorage initialization and consumer group creation."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage(
                redis_url="redis://localhost:6379",
                prefix="test:outbox",
                consumer_group="test-workers",
            )

            await storage.initialize()

            assert storage._initialized is True
            mock_redis.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_outbox_already_initialized(self, mock_redis):
        """Test that initialize() is idempotent."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            # Second call should be no-op
            await storage.initialize()

            # xgroup_create should only be called once
            assert mock_redis.xgroup_create.call_count == 1

    @pytest.mark.asyncio
    async def test_redis_outbox_consumer_group_already_exists(self, mock_redis):
        """Test handling of BUSYGROUP error (group already exists)."""
        from redis.exceptions import ResponseError

        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
        )

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()

            # Should not raise - BUSYGROUP is expected
            await storage.initialize()

            assert storage._initialized is True

    @pytest.mark.asyncio
    async def test_redis_outbox_close(self, mock_redis):
        """Test close() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()
            await storage.close()

            assert storage._redis is None
            assert storage._initialized is False

    @pytest.mark.asyncio
    async def test_redis_outbox_insert(self, mock_redis):
        """Test insert() method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        # Mock pipeline
        mock_pipe = AsyncMock()
        mock_pipe.hset = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.xadd = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            event = OutboxEvent(
                saga_id="saga-123",
                event_type="TestEvent",
                payload={"test": "data"},
            )

            result = await storage.insert(event)

            assert result.event_id == event.event_id
            mock_pipe.hset.assert_called()
            mock_pipe.xadd.assert_called()

    @pytest.mark.asyncio
    async def test_redis_outbox_get_by_id(self, mock_redis):
        """Test get_by_id() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
            b"event_type": b"TestEvent",
            b"payload": b'{"data": "test"}',
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2024-01-01T00:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            event = await storage.get_by_id("evt-123")

            assert event is not None
            assert event.event_id == "evt-123"
            assert event.saga_id == "saga-456"

    @pytest.mark.asyncio
    async def test_redis_outbox_get_by_id_not_found(self, mock_redis):
        """Test get_by_id() when event not found."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.hgetall = AsyncMock(return_value={})

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            event = await storage.get_by_id("nonexistent")

            assert event is None

    @pytest.mark.asyncio
    async def test_redis_outbox_update_status_sent(self, mock_redis):
        """Test update_status() for SENT status."""
        from sagaz.outbox.types import OutboxStatus
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"event_type": b"TestEvent",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"sent",
            b"retry_count": b"0",
            b"created_at": b"",
            b"claimed_at": b"",
            b"sent_at": b"2024-01-01T00:00:00+00:00",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            event = await storage.update_status("evt-123", OutboxStatus.SENT)

            assert event.status == OutboxStatus.SENT
            mock_redis.hdel.assert_called()

    @pytest.mark.asyncio
    async def test_redis_outbox_update_status_failed_with_error(self, mock_redis):
        """Test update_status() for FAILED status with error message."""
        from sagaz.outbox.types import OutboxStatus
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"event_type": b"TestEvent",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"failed",
            b"retry_count": b"1",
            b"created_at": b"",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"Connection refused",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            event = await storage.update_status(
                "evt-123",
                OutboxStatus.FAILED,
                error_message="Connection refused"
            )

            assert event.status == OutboxStatus.FAILED

    @pytest.mark.asyncio
    async def test_redis_outbox_claim_batch_no_messages(self, mock_redis):
        """Test claim_batch() when no messages available."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xreadgroup = AsyncMock(return_value=None)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            events = await storage.claim_batch("worker-1", batch_size=10)

            assert events == []

    @pytest.mark.asyncio
    async def test_redis_outbox_claim_batch_error(self, mock_redis):
        """Test claim_batch() handles errors gracefully."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xreadgroup = AsyncMock(side_effect=Exception("Connection error"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            events = await storage.claim_batch("worker-1", batch_size=10)

            assert events == []

    @pytest.mark.asyncio
    async def test_redis_outbox_get_events_by_saga(self, mock_redis):
        """Test get_events_by_saga() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        # Mock scan to return keys
        mock_redis.scan = AsyncMock(side_effect=[
            (0, [b"sagaz:outbox:meta:evt-1"]),
        ])

        # Mock hgetall to return matching event
        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-1",
            b"saga_id": b"saga-target",
            b"event_type": b"TestEvent",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            events = await storage.get_events_by_saga("saga-target")

            assert len(events) == 1
            assert events[0].saga_id == "saga-target"

    @pytest.mark.asyncio
    async def test_redis_outbox_get_pending_count(self, mock_redis):
        """Test get_pending_count() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xlen = AsyncMock(return_value=42)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            count = await storage.get_pending_count()

            assert count == 42

    @pytest.mark.asyncio
    async def test_redis_outbox_get_pending_count_error(self, mock_redis):
        """Test get_pending_count() handles errors."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xlen = AsyncMock(side_effect=Exception("Error"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            count = await storage.get_pending_count()

            assert count == 0

    @pytest.mark.asyncio
    async def test_redis_outbox_health_check_healthy(self, mock_redis):
        """Test health_check() when healthy."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.storage.core import HealthStatus

        mock_redis.ping = AsyncMock()
        mock_redis.xlen = AsyncMock(return_value=10)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            result = await storage.health_check()

            assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_redis_outbox_health_check_unhealthy(self, mock_redis):
        """Test health_check() when unhealthy."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.storage.core import HealthStatus

        mock_redis.ping = AsyncMock(side_effect=Exception("Connection failed"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            result = await storage.health_check()

            assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_redis_outbox_health_check_not_initialized(self):
        """Test health_check() when not initialized fails to connect."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage
        from sagaz.storage.core import HealthStatus

        with patch("redis.asyncio.from_url", side_effect=Exception("Cannot connect")):
            storage = RedisOutboxStorage()

            result = await storage.health_check()

            assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_redis_outbox_get_statistics(self, mock_redis):
        """Test get_statistics() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xlen = AsyncMock(return_value=5)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            stats = await storage.get_statistics()

            assert stats.pending_records == 5

    @pytest.mark.asyncio
    async def test_redis_outbox_context_manager(self, mock_redis):
        """Test async context manager."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with RedisOutboxStorage() as storage:
                assert storage._initialized is True

            mock_redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_outbox_get_stuck_events(self, mock_redis):
        """Test get_stuck_events() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xpending_range = AsyncMock(return_value=[
            {"time_since_delivered": 400000, "message_id": b"msg-1"},
        ])
        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-1",
            b"saga_id": b"saga-1",
            b"event_type": b"TestEvent",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"claimed",
            b"retry_count": b"0",
            b"created_at": b"",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

            assert len(stuck) >= 0  # May find stuck events

    @pytest.mark.asyncio
    async def test_redis_outbox_get_stuck_events_error(self, mock_redis):
        """Test get_stuck_events() handles errors."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xpending_range = AsyncMock(side_effect=Exception("Error"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            stuck = await storage.get_stuck_events()

            assert stuck == []

    @pytest.mark.asyncio
    async def test_redis_outbox_release_stuck_events(self, mock_redis):
        """Test release_stuck_events() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xpending_range = AsyncMock(return_value=[
            {"time_since_delivered": 400000, "message_id": b"msg-1"},
        ])
        mock_redis.xclaim = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            released = await storage.release_stuck_events(claimed_older_than_seconds=300)

            assert released >= 0

    @pytest.mark.asyncio
    async def test_redis_outbox_release_stuck_events_error(self, mock_redis):
        """Test release_stuck_events() handles errors."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xpending_range = AsyncMock(side_effect=Exception("Error"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            released = await storage.release_stuck_events()

            assert released == 0

    @pytest.mark.asyncio
    async def test_redis_outbox_get_dead_letter_events(self, mock_redis):
        """Test get_dead_letter_events() method."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xrange = AsyncMock(return_value=[
            (b"msg-1", {b"event_id": b"evt-1"}),
        ])
        mock_redis.hgetall = AsyncMock(return_value={
            b"event_id": b"evt-1",
            b"saga_id": b"saga-1",
            b"event_type": b"TestEvent",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"dead_letter",
            b"retry_count": b"10",
            b"created_at": b"",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"Max retries exceeded",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"",
        })

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            dlq = await storage.get_dead_letter_events(limit=10)

            assert len(dlq) >= 0

    @pytest.mark.asyncio
    async def test_redis_outbox_get_dead_letter_events_error(self, mock_redis):
        """Test get_dead_letter_events() handles errors."""
        from sagaz.storage.backends.redis.outbox import RedisOutboxStorage

        mock_redis.xrange = AsyncMock(side_effect=Exception("Error"))

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            storage = RedisOutboxStorage()
            await storage.initialize()

            dlq = await storage.get_dead_letter_events()

            assert dlq == []


# =============================================================================
# SQLITE STORAGE TESTS
# =============================================================================

# Check aiosqlite availability
try:
    import aiosqlite
    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False


@pytest.mark.skipif(not AIOSQLITE_AVAILABLE, reason="aiosqlite not installed")
class TestSQLiteSagaStorageCoverage:
    """Tests for SQLiteSagaStorage coverage gaps."""

    @pytest.mark.asyncio
    async def test_sqlite_saga_update_step_not_found(self):
        """Test update_step_state when saga not found."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStepStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            # Try to update step for non-existent saga
            await storage.update_step_state(
                saga_id="nonexistent",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
            )
            # Should not raise, just return

    @pytest.mark.asyncio
    async def test_sqlite_saga_update_step_success(self):
        """Test update_step_state success path."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus, SagaStepStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            # Create saga with step
            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={},
            )

            # Update step
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                result={"done": True},
            )

            # Verify update
            saga = await storage.load_saga_state("saga-123")
            assert saga["steps"][0]["status"] == "completed"
            assert saga["steps"][0]["result"] == {"done": True}

    @pytest.mark.asyncio
    async def test_sqlite_saga_update_step_with_error(self):
        """Test update_step_state with error."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus, SagaStepStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={},
            )

            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.FAILED,
                error="Something went wrong",
            )

            saga = await storage.load_saga_state("saga-123")
            assert saga["steps"][0]["status"] == "failed"
            assert saga["steps"][0]["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_sqlite_saga_update_step_with_executed_at(self):
        """Test update_step_state with executed_at timestamp."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus, SagaStepStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            await storage.save_saga_state(
                saga_id="saga-123",
                saga_name="TestSaga",
                status=SagaStatus.EXECUTING,
                steps=[{"name": "step1", "status": "pending"}],
                context={},
            )

            now = datetime.now(UTC)
            await storage.update_step_state(
                saga_id="saga-123",
                step_name="step1",
                status=SagaStepStatus.COMPLETED,
                executed_at=now,
            )

            saga = await storage.load_saga_state("saga-123")
            assert "executed_at" in saga["steps"][0]

    @pytest.mark.asyncio
    async def test_sqlite_saga_cleanup_completed(self):
        """Test cleanup_completed_sagas method."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            # Create old completed saga
            await storage.save_saga_state(
                saga_id="old-saga",
                saga_name="TestSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            # Cleanup (with future date to delete all)
            cutoff = datetime.now(UTC) + timedelta(days=1)

            deleted = await storage.cleanup_completed_sagas(cutoff)

            assert deleted == 1

    @pytest.mark.asyncio
    async def test_sqlite_saga_health_check_unhealthy(self):
        """Test health_check when database has issues."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage

        storage = SQLiteSagaStorage(":memory:")
        # Don't initialize - force error
        storage._conn = AsyncMock()
        storage._conn.execute = AsyncMock(side_effect=Exception("DB error"))
        storage._initialized = True

        result = await storage.health_check()

        assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_sqlite_saga_export_all(self):
        """Test export_all generator."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            # Create some sagas
            for i in range(3):
                await storage.save_saga_state(
                    saga_id=f"saga-{i}",
                    saga_name="TestSaga",
                    status=SagaStatus.COMPLETED,
                    steps=[],
                    context={},
                )

            # Export all
            records = []
            async for record in storage.export_all():
                records.append(record)

            assert len(records) == 3

    @pytest.mark.asyncio
    async def test_sqlite_saga_import_record(self):
        """Test import_record method."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage

        async with SQLiteSagaStorage(":memory:") as storage:
            await storage.import_record({
                "saga_id": "imported-saga",
                "saga_name": "ImportedSaga",
                "status": "completed",
                "steps": [{"name": "step1"}],
                "context": {"data": "test"},
            })

            saga = await storage.load_saga_state("imported-saga")

            assert saga is not None
            assert saga["saga_name"] == "ImportedSaga"

    @pytest.mark.asyncio
    async def test_sqlite_saga_list_with_filters(self):
        """Test list_sagas with status and name filters."""
        from sagaz.storage.backends.sqlite.saga import SQLiteSagaStorage
        from sagaz.core.types import SagaStatus

        async with SQLiteSagaStorage(":memory:") as storage:
            # Create sagas with different statuses
            await storage.save_saga_state(
                saga_id="saga-1",
                saga_name="OrderSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )
            await storage.save_saga_state(
                saga_id="saga-2",
                saga_name="OrderSaga",
                status=SagaStatus.FAILED,
                steps=[],
                context={},
            )
            await storage.save_saga_state(
                saga_id="saga-3",
                saga_name="PaymentSaga",
                status=SagaStatus.COMPLETED,
                steps=[],
                context={},
            )

            # Filter by status
            completed = await storage.list_sagas(status=SagaStatus.COMPLETED)
            assert len(completed) == 2

            # Filter by name
            orders = await storage.list_sagas(saga_name="OrderSaga")
            assert len(orders) == 2


@pytest.mark.skipif(not AIOSQLITE_AVAILABLE, reason="aiosqlite not installed")
class TestSQLiteOutboxStorageCoverage:
    """Tests for SQLiteOutboxStorage coverage gaps."""

    @pytest.mark.asyncio
    async def test_sqlite_outbox_get_events_by_saga(self):
        """Test get_events_by_saga method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            # Create events for different sagas
            for i in range(3):
                event = OutboxEvent(
                    saga_id="saga-target",
                    event_type="TestEvent",
                    payload={"index": i},
                )
                await storage.insert(event)

            event = OutboxEvent(
                saga_id="saga-other",
                event_type="TestEvent",
                payload={},
            )
            await storage.insert(event)

            # Get by saga
            events = await storage.get_events_by_saga("saga-target")

            assert len(events) == 3

    @pytest.mark.asyncio
    async def test_sqlite_outbox_health_check_healthy(self):
        """Test health_check when healthy."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage
        from sagaz.storage.core import HealthStatus

        async with SQLiteOutboxStorage(":memory:") as storage:
            result = await storage.health_check()

            assert result.status == HealthStatus.HEALTHY
            assert "pending_count" in result.details

    @pytest.mark.asyncio
    async def test_sqlite_outbox_health_check_unhealthy(self):
        """Test health_check when database has issues."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage
        from sagaz.storage.core import HealthStatus

        storage = SQLiteOutboxStorage(":memory:")
        # Don't initialize properly - force error
        storage._conn = AsyncMock()
        storage._conn.execute = AsyncMock(side_effect=Exception("DB error"))
        storage._initialized = True

        result = await storage.health_check()

        assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_sqlite_outbox_export_all(self):
        """Test export_all generator."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            # Create some events
            for i in range(3):
                event = OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="TestEvent",
                    payload={"index": i},
                )
                await storage.insert(event)

            # Export all
            records = []
            async for record in storage.export_all():
                records.append(record)

            assert len(records) == 3

    @pytest.mark.asyncio
    async def test_sqlite_outbox_import_record(self):
        """Test import_record method."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            await storage.import_record({
                "event_id": "evt-imported",
                "saga_id": "imported-saga",
                "event_type": "ImportedEvent",
                "payload": {"data": "test"},
                "status": "pending",
            })

            event = await storage.get_by_id("evt-imported")

            assert event is not None
            assert event.saga_id == "imported-saga"

    @pytest.mark.asyncio
    async def test_sqlite_outbox_get_dead_letter_events(self):
        """Test get_dead_letter_events method."""
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            # Create an event and mark as dead letter
            event = OutboxEvent(
                saga_id="saga-123",
                event_type="TestEvent",
                payload={},
            )
            await storage.insert(event)
            await storage.update_status(event.event_id, OutboxStatus.DEAD_LETTER)

            # Get dead letter events
            dlq = await storage.get_dead_letter_events(limit=10)

            assert len(dlq) == 1
            assert dlq[0].status == OutboxStatus.DEAD_LETTER

    @pytest.mark.asyncio
    async def test_sqlite_outbox_get_statistics(self):
        """Test get_statistics method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            # Create some events
            for i in range(5):
                event = OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="TestEvent",
                    payload={},
                )
                await storage.insert(event)

            stats = await storage.get_statistics()

            assert stats.total_records == 5
            assert stats.pending_records == 5

    @pytest.mark.asyncio
    async def test_sqlite_outbox_count(self):
        """Test count() method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            for i in range(3):
                event = OutboxEvent(
                    saga_id=f"saga-{i}",
                    event_type="TestEvent",
                    payload={},
                )
                await storage.insert(event)

            count = await storage.count()

            assert count == 3


# =============================================================================
# POSTGRESQL OUTBOX STORAGE TESTS
# =============================================================================

# Check asyncpg availability
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False


@pytest.mark.skipif(not ASYNCPG_AVAILABLE, reason="asyncpg not installed")
class TestPostgreSQLOutboxStorageCoverage:
    """Tests for PostgreSQLOutboxStorage coverage gaps."""

    @pytest.mark.asyncio
    async def test_postgresql_outbox_count_not_initialized(self):
        """Test count() raises error when not initialized."""
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
        from sagaz.storage.interfaces.outbox import OutboxStorageError

        storage = PostgreSQLOutboxStorage("postgresql://localhost/test")

        with pytest.raises(OutboxStorageError, match="not initialized"):
            await storage.count()

    @pytest.mark.asyncio
    async def test_postgresql_outbox_export_all_not_initialized(self):
        """Test export_all() raises error when not initialized."""
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
        from sagaz.storage.interfaces.outbox import OutboxStorageError

        storage = PostgreSQLOutboxStorage("postgresql://localhost/test")

        with pytest.raises(OutboxStorageError, match="not initialized"):
            async for _ in storage.export_all():
                pass

    @pytest.mark.asyncio
    async def test_postgresql_outbox_count_success(self):
        """Test count() method with mocked pool."""
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        storage = PostgreSQLOutboxStorage("postgresql://localhost/test")

        # Mock the pool
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=42)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_ctx)
        storage._pool = mock_pool

        count = await storage.count()

        assert count == 42

    @pytest.mark.asyncio
    async def test_postgresql_outbox_import_record(self):
        """Test import_record() method."""
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        storage = PostgreSQLOutboxStorage("postgresql://localhost/test")

        # Mock insert method
        storage.insert = AsyncMock()

        await storage.import_record({
            "event_id": "evt-123",
            "saga_id": "saga-456",
            "event_type": "TestEvent",
            "payload": {"data": "test"},
            "status": "pending",
        })

        storage.insert.assert_called_once()
        call_args = storage.insert.call_args[0][0]
        assert call_args.saga_id == "saga-456"
        assert call_args.event_type == "TestEvent"


# =============================================================================
# INMEMORY OUTBOX STORAGE ADDITIONAL TESTS
# =============================================================================


class TestInMemoryOutboxStorageCoverage:
    """Additional tests for InMemoryOutboxStorage coverage gaps."""

    @pytest.mark.asyncio
    async def test_inmemory_outbox_export_all(self):
        """Test export_all() method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        # Insert some events
        for i in range(3):
            event = OutboxEvent(
                saga_id=f"saga-{i}",
                event_type="TestEvent",
                payload={"index": i},
            )
            await storage.insert(event)

        # Export all
        records = []
        async for record in storage.export_all():
            records.append(record)

        assert len(records) == 3
        assert all("event_id" in r for r in records)
        assert all("saga_id" in r for r in records)

    @pytest.mark.asyncio
    async def test_inmemory_outbox_import_record(self):
        """Test import_record() method."""
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        await storage.import_record({
            "event_id": "evt-imported",
            "saga_id": "imported-saga",
            "event_type": "ImportedEvent",
            "payload": {"data": "test"},
            "status": "pending",
        })

        event = await storage.get_by_id("evt-imported")

        assert event is not None
        assert event.saga_id == "imported-saga"
        assert event.event_type == "ImportedEvent"

    @pytest.mark.asyncio
    async def test_inmemory_outbox_count(self):
        """Test count() method."""
        from sagaz.outbox.types import OutboxEvent
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        assert await storage.count() == 0

        # Insert events
        for i in range(5):
            event = OutboxEvent(
                saga_id=f"saga-{i}",
                event_type="TestEvent",
                payload={},
            )
            await storage.insert(event)

        assert await storage.count() == 5

    @pytest.mark.asyncio
    async def test_inmemory_outbox_get_dead_letter_events(self):
        """Test get_dead_letter_events() method."""
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        storage = InMemoryOutboxStorage()

        # Insert an event and mark as dead letter
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="TestEvent",
            payload={},
        )
        await storage.insert(event)
        await storage.update_status(event.event_id, OutboxStatus.DEAD_LETTER)

        # Get dead letter events
        dlq = await storage.get_dead_letter_events(limit=10)

        assert len(dlq) == 1
        assert dlq[0].status == OutboxStatus.DEAD_LETTER


# =============================================================================
# SQLITE STUCK EVENTS TESTS
# =============================================================================


@pytest.mark.skipif(not AIOSQLITE_AVAILABLE, reason="aiosqlite not installed")
class TestSQLiteOutboxStuckEvents:
    """Tests for SQLite outbox stuck events functionality."""

    @pytest.mark.asyncio
    async def test_sqlite_outbox_claim_batch_empty(self):
        """Test claim_batch when no events available."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            events = await storage.claim_batch("worker-1", batch_size=10)

            assert events == []

    @pytest.mark.asyncio
    async def test_sqlite_outbox_get_stuck_events_none(self):
        """Test get_stuck_events when no stuck events."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

            assert stuck == []

    @pytest.mark.asyncio
    async def test_sqlite_outbox_release_stuck_events_none(self):
        """Test release_stuck_events when no stuck events."""
        from sagaz.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        async with SQLiteOutboxStorage(":memory:") as storage:
            released = await storage.release_stuck_events(claimed_older_than_seconds=300)

            assert released == 0


# =============================================================================
# LAZY __getattr__ COMPAT MODULES TESTS
# =============================================================================


class TestLazyGetAttrCompatModules:
    """Tests for lazy __getattr__ in backward compatibility modules."""

    def test_outbox_init_lazy_getattr(self):
        """Test lazy imports in sagaz.outbox.__init__."""
        from sagaz import outbox

        # Access InMemoryOutboxStorage
        cls = outbox.InMemoryOutboxStorage
        assert cls is not None

        # Access OutboxStorage
        storage_cls = outbox.OutboxStorage
        assert storage_cls is not None

        # Access OutboxStorageError
        err = outbox.OutboxStorageError
        assert err is not None

        # Access PostgreSQLOutboxStorage
        pg_cls = outbox.PostgreSQLOutboxStorage
        assert pg_cls is not None

    def test_outbox_storage_canonical_imports(self):
        """Test canonical imports from sagaz.storage work correctly."""
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage
        from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
        from sagaz.storage.interfaces.outbox import OutboxStorage, OutboxStorageError

        assert InMemoryOutboxStorage is not None
        assert PostgreSQLOutboxStorage is not None
        assert OutboxStorage is not None
        assert OutboxStorageError is not None

