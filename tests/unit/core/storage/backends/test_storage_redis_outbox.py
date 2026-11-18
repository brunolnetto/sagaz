"""
Tests for Redis Outbox Storage.
"""

from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class TestRedisOutboxStorageUnit:
    """Unit tests for RedisOutboxStorage with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.xlen = AsyncMock(return_value=10)
        mock.xgroup_create = AsyncMock()
        mock.xadd = AsyncMock(return_value=b"1234567890-0")
        mock.xreadgroup = AsyncMock(return_value=[])
        mock.xrange = AsyncMock(return_value=[])
        mock.xpending_range = AsyncMock(return_value=[])
        mock.xack = AsyncMock()
        mock.hset = AsyncMock()
        mock.hgetall = AsyncMock(return_value={})
        mock.hdel = AsyncMock()
        mock.expire = AsyncMock()
        mock.scan = AsyncMock(return_value=(0, []))
        mock.close = AsyncMock()

        # Pipeline mock
        pipeline_mock = AsyncMock()
        pipeline_mock.watch = AsyncMock()
        pipeline_mock.hgetall = AsyncMock(return_value={})
        pipeline_mock.unwatch = AsyncMock()
        pipeline_mock.multi = MagicMock()
        pipeline_mock.hset = MagicMock()
        pipeline_mock.expire = MagicMock()
        pipeline_mock.xadd = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[True, True, b"1234567890-0"])
        pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock)
        pipeline_mock.__aexit__ = AsyncMock(return_value=None)
        mock.pipeline = MagicMock(return_value=pipeline_mock)

        return mock

    @pytest.fixture
    async def storage(self, mock_redis):
        """Create storage with mocked Redis."""
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            from sagaz.core.storage.backends.redis import RedisOutboxStorage

            storage = RedisOutboxStorage(
                redis_url="redis://localhost:6379",
                prefix="test:outbox",
                consumer_group="test-workers",
            )
            await storage.initialize()
            yield storage
            await storage.close()

    @pytest.mark.asyncio
    async def test_initialization(self, mock_redis):
        """Test storage initialization creates consumer group."""
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            from sagaz.core.storage.backends.redis import RedisOutboxStorage

            storage = RedisOutboxStorage(prefix="test:outbox")
            await storage.initialize()

            mock_redis.xgroup_create.assert_called_once()
            assert storage._initialized is True

            await storage.close()

    @pytest.mark.asyncio
    async def test_initialization_group_exists(self, mock_redis):
        """Test initialization handles existing consumer group."""
        import redis

        mock_redis.xgroup_create.side_effect = redis.ResponseError("BUSYGROUP")

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            from sagaz.core.storage.backends.redis import RedisOutboxStorage

            storage = RedisOutboxStorage()
            await storage.initialize()

            assert storage._initialized is True
            await storage.close()

    @pytest.mark.asyncio
    async def test_insert_event(self, storage, mock_redis):
        """Test inserting an outbox event."""
        event = OutboxEvent(
            saga_id="saga-456",
            event_type="OrderCreated",
            payload={"order_id": "123", "amount": 99.99},
        )

        result = await storage.insert(event)

        assert result.event_id is not None
        assert result.saga_id == "saga-456"
        # Verify pipeline was used
        mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, storage, mock_redis):
        """Test getting an event by ID when it exists."""
        mock_redis.hgetall.return_value = {
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"saga-456",
            b"event_type": b"OrderCreated",
            b"payload": b'{"order_id": "123"}',
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }

        event = await storage.get_by_id("evt-123")

        assert event is not None
        assert event.event_id == "evt-123"
        assert event.saga_id == "saga-456"
        assert event.status == OutboxStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, storage, mock_redis):
        """Test getting an event by ID when it doesn't exist."""
        mock_redis.hgetall.return_value = {}

        event = await storage.get_by_id("nonexistent")

        assert event is None

    @pytest.mark.asyncio
    async def test_update_status_sent(self, storage, mock_redis):
        """Test updating event status to SENT."""
        mock_redis.hgetall.return_value = {
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"saga-456",
            b"event_type": b"OrderCreated",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"sent",
            b"retry_count": b"0",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"2024-01-15T10:01:00+00:00",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }

        event = await storage.update_status("evt-123", OutboxStatus.SENT)

        assert event.status == OutboxStatus.SENT
        mock_redis.hdel.assert_called()  # Removed from processing

    @pytest.mark.asyncio
    async def test_update_status_failed_with_error(self, storage, mock_redis):
        """Test updating event status to FAILED with error message."""
        mock_redis.hgetall.return_value = {
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"saga-456",
            b"event_type": b"OrderCreated",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"failed",
            b"retry_count": b"3",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"Connection timeout",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }

        event = await storage.update_status(
            "evt-123",
            OutboxStatus.FAILED,
            error_message="Connection timeout",
        )

        assert event.status == OutboxStatus.FAILED

    @pytest.mark.asyncio
    async def test_claim_batch_empty(self, storage, mock_redis):
        """Test claiming batch when no events available."""
        mock_redis.xreadgroup.return_value = []

        events = await storage.claim_batch("worker-1", batch_size=10)

        assert events == []

    @pytest.mark.asyncio
    async def test_claim_batch_with_events(self, storage, mock_redis):
        """Test claiming batch with available events."""
        # Mock stream response
        mock_redis.xreadgroup.return_value = [
            (
                b"test:outbox:events",
                [
                    (
                        b"1234567890-0",
                        {
                            b"event_id": b"evt-123",
                            b"saga_id": b"saga-456",
                            b"event_type": b"OrderCreated",
                        },
                    ),
                ],
            )
        ]

        # Mock get_by_id response
        mock_redis.hgetall.return_value = {
            b"event_id": b"evt-123",
            b"saga_id": b"saga-456",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"saga-456",
            b"event_type": b"OrderCreated",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }

        events = await storage.claim_batch("worker-1", batch_size=10)

        assert len(events) == 1
        assert events[0].event_id == "evt-123"
        assert events[0].status == OutboxStatus.CLAIMED
        assert events[0].worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_get_pending_count(self, storage, mock_redis):
        """Pending count is the consumer group's lag, not the stream length."""
        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups = AsyncMock(
            return_value=[
                {"name": b"other-workers", "lag": 7},
                {"name": b"test-workers", "lag": 42, "last-delivered-id": b"5-0"},
            ]
        )

        count = await storage.get_pending_count()

        assert count == 42

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, storage, mock_redis):
        """Test health check when Redis is healthy."""
        mock_redis.ping.return_value = True
        mock_redis.xlen.return_value = 10

        result = await storage.health_check()

        assert result.status.value == "healthy"
        assert result.is_healthy is True
        assert result.details["stream_length"] == 10

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, storage, mock_redis):
        """Test health check when Redis fails."""
        mock_redis.ping.side_effect = Exception("Connection refused")

        result = await storage.health_check()

        assert result.status.value == "unhealthy"
        assert result.is_healthy is False
        assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_get_statistics(self, storage, mock_redis):
        """Test getting storage statistics."""
        mock_redis.xinfo_groups = AsyncMock(return_value=[{"name": b"test-workers", "lag": 25}])
        mock_redis.xlen.return_value = 3  # dlq

        stats = await storage.get_statistics()

        assert stats.pending_records == 25
        assert stats.failed_records == 3

    @pytest.mark.asyncio
    async def test_get_dead_letter_events(self, storage, mock_redis):
        """Test getting dead letter events."""
        mock_redis.xrange.return_value = []

        events = await storage.get_dead_letter_events(limit=10)

        assert events == []

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_redis):
        """Test using storage as context manager."""
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            from sagaz.core.storage.backends.redis import RedisOutboxStorage

            async with RedisOutboxStorage() as storage:
                assert storage._initialized is True

            mock_redis.close.assert_called()

    @pytest.mark.asyncio
    async def test_count_includes_sent_failed_and_dead_letter_events(self, storage, mock_redis):
        """Count all metadata records, not only pending stream entries."""
        mock_redis.scan.side_effect = [
            (1, [b"test:outbox:meta:pending", b"test:outbox:meta:sent"]),
            (0, [b"test:outbox:meta:dead-letter"]),
        ]

        count = await storage.count()

        assert count == 3
        assert mock_redis.scan.call_count == 2

    @pytest.mark.asyncio
    async def test_export_all(self, storage, mock_redis):
        """Test exporting all events."""
        # Mock scan to return event keys
        mock_redis.scan.side_effect = [
            (1, [b"test:outbox:meta:evt-1", b"test:outbox:meta:evt-2"]),
            (0, [b"test:outbox:meta:evt-3"]),
        ]
        mock_redis.hgetall.side_effect = [
            {
                b"event_id": b"evt-1",
                b"saga_id": b"saga-1",
                b"aggregate_type": b"saga",
                b"aggregate_id": b"saga-1",
                b"event_type": b"Test",
                b"payload": b"{}",
                b"headers": b"{}",
                b"status": b"pending",
                b"retry_count": b"0",
                b"created_at": b"2024-01-15T10:00:00+00:00",
                b"claimed_at": b"",
                b"sent_at": b"",
                b"last_error": b"",
                b"worker_id": b"",
                b"routing_key": b"",
                b"partition_key": b"",
            },
            {
                b"event_id": b"evt-2",
                b"saga_id": b"saga-2",
                b"aggregate_type": b"saga",
                b"aggregate_id": b"saga-2",
                b"event_type": b"Test",
                b"payload": b"{}",
                b"headers": b"{}",
                b"status": b"sent",
                b"retry_count": b"0",
                b"created_at": b"2024-01-15T10:00:00+00:00",
                b"claimed_at": b"",
                b"sent_at": b"2024-01-15T10:01:00+00:00",
                b"last_error": b"",
                b"worker_id": b"",
                b"routing_key": b"",
                b"partition_key": b"",
            },
            {
                b"event_id": b"evt-3",
                b"saga_id": b"saga-3",
                b"aggregate_type": b"saga",
                b"aggregate_id": b"saga-3",
                b"event_type": b"Test",
                b"payload": b"{}",
                b"headers": b"{}",
                b"status": b"pending",
                b"retry_count": b"0",
                b"created_at": b"2024-01-15T10:00:00+00:00",
                b"claimed_at": b"",
                b"sent_at": b"",
                b"last_error": b"",
                b"worker_id": b"",
                b"routing_key": b"",
                b"partition_key": b"",
            },
        ]

        events = []
        async for event in storage.export_all():
            events.append(event)

        assert len(events) == 3
        assert events[0]["event_id"] == "evt-1"
        assert events[1]["event_id"] == "evt-2"
        assert events[2]["event_id"] == "evt-3"
        assert events[0]["routing_key"] is None
        assert events[0]["partition_key"] is None

    @pytest.mark.asyncio
    async def test_export_all_empty(self, storage, mock_redis):
        """Test exporting when no events exist."""
        mock_redis.scan.return_value = (0, [])

        events = []
        async for event in storage.export_all():
            events.append(event)

        assert events == []

    @pytest.mark.asyncio
    async def test_import_record(self, storage, mock_redis):
        """Test importing a record."""
        record = {
            "event_id": "evt-imported",
            "saga_id": "saga-imported",
            "event_type": "ImportedEvent",
            "payload": {"imported": True},
            "status": "pending",
        }

        await storage.import_record(record)

        # Verify insert was called via pipeline
        mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_import_dead_letter_record_does_not_enqueue_delivery(self, storage, mock_redis):
        """Terminal events are stored as metadata, not added to the delivery stream."""
        record = {
            "event_id": "event-dlq",
            "saga_id": "saga-dlq",
            "event_type": "OrderFailed",
            "payload": {"order_id": "123"},
            "status": "dead_letter",
            "dead_letter_reason": "max_retries_exceeded",
            "routing_key": "orders.failed",
            "partition_key": "tenant-a",
        }

        await storage.import_record(record)

        pipeline = mock_redis.pipeline.return_value
        pipeline.hset.assert_called()
        pipeline.expire.assert_called()
        pipeline.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_reimport_existing_pending_record_does_not_duplicate_stream(
        self, storage, mock_redis
    ):
        """An identical re-import is a no-op."""
        pipeline = mock_redis.pipeline.return_value
        pipeline.hgetall.return_value = {
            b"event_id": b"event-pending",
            b"saga_id": b"saga-pending",
            b"aggregate_type": b"order",
            b"aggregate_id": b"order-123",
            b"event_type": b"OrderCreated",
            b"payload": b'{"order_id":"123"}',
            b"headers": b'{"trace_id":"trace-1"}',
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2026-01-01T00:00:00+00:00",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"orders.created",
            b"partition_key": b"tenant-a",
            b"dead_letter_at": b"",
            b"dead_letter_reason": b"",
            b"error_type": b"",
            b"error_classification": b"",
            b"error_fingerprint": b"",
            b"replay_count": b"0",
        }
        record = {
            "event_id": "event-pending",
            "saga_id": "saga-pending",
            "aggregate_type": "order",
            "aggregate_id": "order-123",
            "event_type": "OrderCreated",
            "payload": {"order_id": "123"},
            "headers": {"trace_id": "trace-1"},
            "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
            "routing_key": "orders.created",
            "partition_key": "tenant-a",
        }

        await storage.import_record(record)

        pipeline.hset.assert_not_called()
        pipeline.xadd.assert_not_called()
        pipeline.execute.assert_not_awaited()
        pipeline.unwatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_rejects_stale_state_without_overwriting_sent_event(
        self, storage, mock_redis
    ):
        from sagaz.core.storage.interfaces.outbox import OutboxStorageError

        sent_at = datetime(2026, 1, 1, tzinfo=UTC)
        existing = OutboxEvent(
            event_id="event-already-sent",
            saga_id="saga-1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            status=OutboxStatus.SENT,
            sent_at=sent_at,
        )
        pipeline = mock_redis.pipeline.return_value
        pipeline.hgetall.return_value = {
            key.encode(): value.encode()
            for key, value in storage._serialize_event(existing).items()
        }

        stale_snapshot = existing.to_dict()
        stale_snapshot["status"] = OutboxStatus.PENDING.value
        stale_snapshot["sent_at"] = None

        with pytest.raises(OutboxStorageError, match="different state"):
            await storage.import_record(stale_snapshot)

        pipeline.hset.assert_not_called()
        pipeline.xadd.assert_not_called()
        pipeline.execute.assert_not_awaited()

    async def test_import_record_without_optional_fields(self, storage, mock_redis):
        """Test importing a minimal record."""
        record = {
            "saga_id": "saga-minimal",
            "event_type": "MinimalEvent",
        }

        await storage.import_record(record)

        mock_redis.pipeline.assert_called()


@pytest.mark.integration
class TestRedisOutboxStorageIntegration:
    """Integration tests requiring real Redis via testcontainers."""

    @pytest.fixture
    async def storage(self, redis_url):
        """Create storage with real Redis from testcontainers."""
        if not redis_url:
            pytest.skip("Redis container not available")

        # Flush DB first to ensure clean state
        import redis.asyncio as redis

        temp_client = redis.from_url(redis_url)
        await temp_client.flushdb()
        await temp_client.aclose() if hasattr(temp_client, "aclose") else await temp_client.close()

        from sagaz.core.storage.backends.redis import RedisOutboxStorage

        storage = RedisOutboxStorage(
            redis_url=redis_url,
            prefix="test:outbox",
            consumer_group="test-workers",
        )
        await storage.initialize()

        yield storage

        # Cleanup
        if storage._redis:
            await storage._redis.flushdb()
        await storage.close()

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, storage):
        """Test complete event lifecycle: insert -> claim -> sent."""
        # Insert event
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="TestEvent",
            payload={"key": "value"},
        )

        inserted = await storage.insert(event)
        assert inserted.event_id is not None
        assert inserted.status == OutboxStatus.PENDING

        # Verify in storage
        retrieved = await storage.get_by_id(inserted.event_id)
        assert retrieved is not None
        assert retrieved.saga_id == "saga-123"

        # Claim event
        claimed = await storage.claim_batch("test-worker", batch_size=10)
        assert len(claimed) == 1
        assert claimed[0].event_id == inserted.event_id
        assert claimed[0].status == OutboxStatus.CLAIMED
        assert claimed[0].worker_id == "test-worker"

        # Mark as sent
        sent = await storage.update_status(inserted.event_id, OutboxStatus.SENT)
        assert sent.status == OutboxStatus.SENT
        assert sent.sent_at is not None

    @pytest.mark.asyncio
    async def test_multiple_workers_claim(self, storage):
        """Test that multiple workers don't claim same events."""
        # Insert multiple events
        for i in range(10):
            await storage.insert(
                OutboxEvent(
                    saga_id="saga-123",
                    event_type="TestEvent",
                    payload={"index": i},
                )
            )

        # Two workers claim concurrently
        claims1 = await storage.claim_batch("worker-1", batch_size=5)
        claims2 = await storage.claim_batch("worker-2", batch_size=5)

        # All events should be claimed by one worker or the other
        claimed_ids = {e.event_id for e in claims1} | {e.event_id for e in claims2}
        assert len(claimed_ids) == len(claims1) + len(claims2)  # No duplicates

    @pytest.mark.asyncio
    async def test_health_check_real(self, storage):
        """Test health check with real Redis."""
        result = await storage.health_check()

        assert result.is_healthy is True
        assert result.latency_ms > 0
