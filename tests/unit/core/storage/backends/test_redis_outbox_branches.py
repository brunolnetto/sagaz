import sys
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from sagaz.core.storage.backends.redis.outbox import OutboxEvent, OutboxStatus, RedisOutboxStorage


@pytest.mark.asyncio
async def test_redis_close_not_connected():
    """Test closing when not connected (covers line 124 -> 127)."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._redis = None
    # Should not raise error
    await storage.close()


@pytest.mark.asyncio
async def test_redis_serialize_minimal_event():
    """Test serialization with minimal fields (covers ternary else branches)."""
    storage = RedisOutboxStorage("redis://localhost")

    event = OutboxEvent(
        event_id="evt-1",
        saga_id="saga-1",
        event_type="test_event",
        payload={"foo": "bar"},
        status=OutboxStatus.PENDING,
        created_at=datetime.now(UTC),
        # All optional fields None
        aggregate_type=None,
        aggregate_id=None,
        headers=None,
        claimed_at=None,
        sent_at=None,
        last_error=None,
        worker_id=None,
        routing_key=None,
        partition_key=None,
    )

    # Force aggregate_id to None to test the fallback, bypassing __post_init__ logic
    event.aggregate_id = None

    data = storage._serialize_event(event)
    assert data["aggregate_type"] == "saga"  # Default
    assert data["aggregate_id"] == ""
    assert data["claimed_at"] == ""
    assert data["sent_at"] == ""


@pytest.mark.asyncio
async def test_update_status_branches():
    """Test update_status with different branch combinations."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()
    storage._redis.hset = AsyncMock()
    storage._redis.hdel = AsyncMock()

    # Mock get_by_id to return something so we don't hit the check at end
    storage.get_by_id = AsyncMock(
        return_value=OutboxEvent(
            event_id="evt-1",
            saga_id="s-1",
            event_type="t",
            payload={},
            status=OutboxStatus.PENDING,
            created_at=datetime.now(UTC),
        )
    )

    # Case 1: Status SENT (hits if status == sentinel)
    await storage.update_status("evt-1", OutboxStatus.SENT)
    # Verify sent_at was set in update
    call_args = storage._redis.hset.call_args[1]
    assert "sent_at" in call_args["mapping"]

    # Case 2: Status FAILED with error (hits elif and condition)
    await storage.update_status("evt-1", OutboxStatus.FAILED, error_message="oops")
    call_args = storage._redis.hset.call_args[1]
    assert call_args["mapping"]["last_error"] == "oops"

    # Case 3: Status FAILED without error (misses error_message condition)
    await storage.update_status("evt-1", OutboxStatus.FAILED, error_message=None)
    call_args = storage._redis.hset.call_args[1]
    assert "last_error" not in call_args["mapping"]

    # Case 4: Other status (misses all ifs)
    await storage.update_status("evt-1", OutboxStatus.PENDING)


# =============================================================================
# Additional coverage: lazy initialize paths, exception handlers, branches
# =============================================================================


def _make_initialized_storage():
    """Helper: storage with _initialized=False and mocked initialize()."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = False
    mock_redis = AsyncMock()

    # pipeline() must be a sync call returning an async context manager
    mock_pipeline = MagicMock()
    mock_pipeline.hset = MagicMock()
    mock_pipeline.expire = MagicMock()
    mock_pipeline.xadd = MagicMock()
    mock_pipeline.execute = AsyncMock()
    mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
    mock_pipeline.__aexit__ = AsyncMock(return_value=False)
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

    async def fake_initialize():
        storage._initialized = True
        storage._redis = mock_redis

    storage.initialize = fake_initialize
    return storage, mock_redis


@pytest.mark.asyncio
async def test_initialize_non_busygroup_reraises():
    """Line 115: non-BUSYGROUP xgroup_create error is re-raised."""
    from unittest.mock import patch

    import redis.asyncio as redis_lib

    storage = RedisOutboxStorage("redis://localhost")

    mock_redis_client = AsyncMock()
    mock_redis_client.xgroup_create = AsyncMock(
        side_effect=redis_lib.ResponseError("WRONGTYPE something")
    )

    with patch("redis.asyncio.from_url", return_value=mock_redis_client):
        with pytest.raises(redis_lib.ResponseError, match="WRONGTYPE"):
            await storage.initialize()


@pytest.mark.asyncio
async def test_insert_lazy_initialize():
    """Line 197: insert() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()

    event = OutboxEvent(
        event_id="lazy-1",
        saga_id="s-1",
        event_type="test",
        payload={"k": "v"},
        status=OutboxStatus.PENDING,
        created_at=datetime.now(UTC),
    )

    result = await storage.insert(event)
    assert result.event_id == "lazy-1"
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_by_id_lazy_initialize():
    """Line 229: get_by_id() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.hgetall = AsyncMock(return_value={})

    result = await storage.get_by_id("nonexistent")
    assert result is None
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_update_status_lazy_initialize():
    """Line 249: update_status() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.hset = AsyncMock()
    mock_redis.hdel = AsyncMock()

    exist_event = OutboxEvent(
        event_id="up-1",
        saga_id="s-1",
        event_type="t",
        payload={},
        status=OutboxStatus.PENDING,
        created_at=datetime.now(UTC),
    )
    storage.get_by_id = AsyncMock(return_value=exist_event)

    await storage.update_status("up-1", OutboxStatus.SENT)
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_update_status_event_not_found():
    """Lines 271-272: update_status raises OutboxStorageError when event missing."""
    from sagaz.core.storage.backends.redis.outbox import OutboxStorageError

    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()
    storage._redis.hset = AsyncMock()
    storage._redis.hdel = AsyncMock()
    storage.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(OutboxStorageError, match="Event not found"):
        await storage.update_status("missing-evt", OutboxStatus.SENT)


@pytest.mark.asyncio
async def test_claim_batch_lazy_initialize():
    """Line 292: claim_batch() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xreadgroup = AsyncMock(return_value=[])

    result = await storage.claim_batch("worker-1")
    assert result == []
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_claim_batch_returns_events():
    """Lines 301-303: claim_batch logs when events returned."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()

    exist_event = OutboxEvent(
        event_id="evt-claim",
        saga_id="s-1",
        event_type="t",
        payload={},
        status=OutboxStatus.PENDING,
        created_at=datetime.now(UTC),
    )
    storage._read_from_stream = AsyncMock(
        return_value=[[("stream", [("msg-1", {b"event_id": b"evt-claim"})])]]
    )
    storage._process_claimed_messages = AsyncMock(return_value=[exist_event])

    result = await storage.claim_batch("worker-1")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_claim_single_message_orphaned():
    """Lines 340, 345-347: orphaned message (event not found) gets xacked and returns None."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()
    storage._redis.xack = AsyncMock()
    storage.get_by_id = AsyncMock(return_value=None)

    result = await storage._claim_single_message(
        b"msg-123",
        {b"event_id": b"orphaned-evt"},
        "worker-1",
        datetime.now(UTC),
    )

    assert result is None
    storage._redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_event_id_empty():
    """Line 362: _extract_event_id returns empty string when no event_id key."""
    storage = RedisOutboxStorage("redis://localhost")
    result = storage._extract_event_id({"other": "data"})
    assert result == ""


@pytest.mark.asyncio
async def test_get_events_by_saga_lazy_initialize():
    """Line 386: get_events_by_saga() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.scan = AsyncMock(return_value=(0, []))

    result = await storage.get_events_by_saga("saga-123")
    assert result == []
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_stuck_events_lazy_initialize():
    """Line 423: get_stuck_events() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xpending_range = AsyncMock(return_value=[])

    result = await storage.get_stuck_events()
    assert result == []
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_stuck_events_with_stuck():
    """Lines 444-452: get_stuck_events finds events over threshold."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()

    stuck_event = OutboxEvent(
        event_id="stuck-1",
        saga_id="s-1",
        event_type="t",
        payload={},
        status=OutboxStatus.CLAIMED,
        created_at=datetime.now(UTC),
    )

    storage._redis.xpending_range = AsyncMock(
        return_value=[
            {"message_id": b"stuck-1", "time_since_delivered": 9999999},
        ]
    )
    storage.get_by_id = AsyncMock(return_value=stuck_event)

    result = await storage.get_stuck_events(claimed_older_than_seconds=1.0)
    assert len(result) == 1
    assert result[0].event_id == "stuck-1"


@pytest.mark.asyncio
async def test_release_stuck_events_lazy_initialize():
    """Line 462: release_stuck_events() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xpending_range = AsyncMock(return_value=[])

    count = await storage.release_stuck_events()
    assert count == 0
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_release_stuck_events_releases():
    """Lines 482-501: release_stuck_events with stuck entries."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()
    storage._redis.xpending_range = AsyncMock(
        return_value=[
            {"message_id": b"msg-stuck", "time_since_delivered": 999999999},
        ]
    )
    storage._redis.xclaim = AsyncMock()

    count = await storage.release_stuck_events(claimed_older_than_seconds=1.0)
    assert count == 1


@pytest.mark.asyncio
async def test_release_stuck_events_claim_failure():
    """Lines 495-496: xclaim failure is logged and continues."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    storage._redis = AsyncMock()
    storage._redis.xpending_range = AsyncMock(
        return_value=[
            {"message_id": b"msg-stuck", "time_since_delivered": 999999999},
        ]
    )
    storage._redis.xclaim = AsyncMock(side_effect=Exception("xclaim failed"))

    count = await storage.release_stuck_events(claimed_older_than_seconds=1.0)
    assert count == 0


@pytest.mark.asyncio
async def test_get_pending_count_lazy_initialize():
    """Line 510: get_pending_count() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xlen = AsyncMock(return_value=5)

    result = await storage.get_pending_count()
    assert result == 5
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_dead_letter_events_lazy_initialize():
    """Line 521: get_dead_letter_events() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xrange = AsyncMock(return_value=[])

    result = await storage.get_dead_letter_events()
    assert result == []
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_statistics_lazy_initialize():
    """Line 582: get_statistics() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.xlen = AsyncMock(return_value=3)

    result = await storage.get_statistics()
    assert result.pending_records == 3
    assert storage._initialized is True


@pytest.mark.asyncio
async def test_get_statistics_xlen_exception():
    """Lines 589-590: get_statistics handles xlen exception gracefully."""
    storage = RedisOutboxStorage("redis://localhost")
    storage._initialized = True
    mock_redis = AsyncMock()
    mock_redis.xlen = AsyncMock(side_effect=Exception("redis down"))
    storage._redis = mock_redis
    storage.get_pending_count = AsyncMock(return_value=0)

    result = await storage.get_statistics()
    assert result.failed_records == 0


@pytest.mark.asyncio
async def test_export_all_lazy_initialize():
    """Line 605: export_all() calls initialize() when not initialized."""
    storage, mock_redis = _make_initialized_storage()
    mock_redis.scan = AsyncMock(return_value=(0, []))

    results = []
    async for event in storage.export_all():
        results.append(event)
    assert results == []
    assert storage._initialized is True


class TestRedisOutboxImportError:
    async def test_initialize_raises_when_redis_unavailable(self):
        """97-99: ImportError during initialize when redis blocked."""
        from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

        storage = RedisOutboxStorage(redis_url="redis://localhost:6379")
        with patch.dict(sys.modules, {"redis": None, "redis.asyncio": None}):
            # Patch from_url to simulate import failure path
            with patch(
                "sagaz.core.storage.backends.redis.outbox.redis",
                new=None,  # redis is None → attribute access fails
                create=True,
            ):
                with pytest.raises((ImportError, AttributeError)):
                    # This will fail because redis.asyncio is patched to None
                    await storage.initialize()


# ==========================================================================
# storage/backends/redis/outbox.py – additional missing branches


class TestRedisOutboxMissingBranches:
    @pytest.fixture
    def mock_redis(self):
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.xlen = AsyncMock(return_value=0)
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
        mock.aclose = AsyncMock()

        pipeline_mock = AsyncMock()
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
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

            storage = RedisOutboxStorage(
                redis_url="redis://localhost:6379",
                prefix="test:outbox",
                consumer_group="test-workers",
            )
            await storage.initialize()
            yield storage
            await storage.close()

    async def test_claim_batch_response_no_valid_events(self, storage, mock_redis):
        """301->304: events is empty after processing → if events: False."""
        # Return a response but with no valid event_id so _claim_single_message returns None
        mock_redis.xreadgroup.return_value = [
            (
                b"test:outbox:events",
                [(b"1234567890-0", {})],  # Empty data → no event_id
            )
        ]
        mock_redis.hgetall.return_value = {}
        events = await storage.claim_batch("worker-1", batch_size=10)
        assert events == []

    async def test_claim_single_message_no_event_id(self, storage, mock_redis):
        """340: _claim_single_message returns None when event_id empty."""
        mock_redis.xreadgroup.return_value = [
            (
                b"test:outbox:events",
                [(b"1234567890-0", {b"event_id": b""})],  # Empty event_id
            )
        ]
        events = await storage.claim_batch("worker-1", batch_size=10)
        assert events == []

    async def test_get_events_by_saga_id_no_match(self, storage, mock_redis):
        """399->397: saga_id in hgetall data doesn't match → skip. 405->397 loop."""
        mock_redis.scan.side_effect = [
            (1, [b"test:outbox:meta:evt-1"]),
            (0, []),
        ]
        mock_redis.hgetall.return_value = {
            b"saga_id": b"different-saga-id",
            b"event_id": b"evt-1",
            b"event_type": b"Test",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"saga-1",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }
        events = await storage.get_events_by_saga("target-saga-id")
        assert events == []

    async def test_get_events_by_saga_id_empty_hgetall(self, storage, mock_redis):
        """399->397 FALSE: hgetall returns {} for first key → skip; second key has data."""
        mock_redis.scan.side_effect = [
            (0, [b"test:outbox:meta:evt-empty", b"test:outbox:meta:evt-data"]),
        ]

        def hgetall_side_effect(key):
            if key == b"test:outbox:meta:evt-empty":
                return {}  # empty → if data: is False → 399->397
            return {
                b"saga_id": b"my-saga-id",
                b"event_id": b"evt-data",
                b"event_type": b"Test",
                b"payload": b"{}",
                b"headers": b"{}",
                b"status": b"pending",
                b"retry_count": b"0",
                b"created_at": b"2024-01-15T10:00:00+00:00",
                b"aggregate_type": b"saga",
                b"aggregate_id": b"my-saga-id",
                b"claimed_at": b"",
                b"sent_at": b"",
                b"last_error": b"",
                b"worker_id": b"",
                b"routing_key": b"",
                b"partition_key": b"",
            }

        mock_redis.hgetall = AsyncMock(side_effect=hgetall_side_effect)
        events = await storage.get_events_by_saga("my-saga-id")
        assert len(events) == 1

    async def test_get_events_by_saga_id_multi_scan_pages(self, storage, mock_redis):
        """408->394: cursor != 0 → multiple scan pages."""
        mock_redis.scan.side_effect = [
            (5, [b"test:outbox:meta:evt-1"]),  # cursor != 0 → continue
            (0, [b"test:outbox:meta:evt-2"]),  # cursor == 0 → break
        ]
        mock_redis.hgetall.return_value = {
            b"saga_id": b"other",
            b"event_id": b"x",
            b"event_type": b"T",
            b"payload": b"{}",
            b"headers": b"{}",
            b"status": b"pending",
            b"retry_count": b"0",
            b"created_at": b"2024-01-15T10:00:00+00:00",
            b"aggregate_type": b"saga",
            b"aggregate_id": b"x",
            b"claimed_at": b"",
            b"sent_at": b"",
            b"last_error": b"",
            b"worker_id": b"",
            b"routing_key": b"",
            b"partition_key": b"",
        }
        await storage.get_events_by_saga("my-saga")

    async def test_find_stuck_events_below_threshold(self, storage, mock_redis):
        """451->442: idle_time <= threshold_ms → skip entry."""
        mock_redis.xpending_range.return_value = [
            {"message_id": b"msg-1", "time_since_delivered": 100},  # Below threshold
        ]
        events = await storage.get_stuck_events(claimed_older_than_seconds=300.0)
        assert events == []

    async def test_find_stuck_events_event_not_found(self, storage, mock_redis):
        """444->442: event is None even though idle_time > threshold."""
        mock_redis.xpending_range.return_value = [
            {"message_id": b"msg-1", "time_since_delivered": 999999},  # Over threshold
        ]
        mock_redis.hgetall.return_value = {}  # get_by_id returns None
        events = await storage.get_stuck_events(claimed_older_than_seconds=1.0)
        assert events == []

    async def test_release_stuck_events_below_threshold(self, storage, mock_redis):
        """482->480: entries below threshold → loop continues without xclaim."""
        mock_redis.xpending_range.return_value = [
            {"message_id": b"msg-1", "time_since_delivered": 50},  # Below threshold
        ]
        released = await storage.release_stuck_events(claimed_older_than_seconds=300.0)
        assert released == 0

    async def test_dead_letter_event_not_found(self, storage, mock_redis):
        """535->528: event is None in get_dead_letter_events."""
        mock_redis.xrange.return_value = [
            (b"msg-1", {b"event_id": b"evt-missing"}),
        ]
        mock_redis.hgetall.return_value = {}  # event not found
        events = await storage.get_dead_letter_events(limit=10)
        assert events == []

    async def test_export_all_empty_hgetall(self, storage, mock_redis):
        """614->612: hgetall returns empty → if data: False."""
        mock_redis.scan.side_effect = [
            (0, [b"test:outbox:meta:evt-1"]),
        ]
        mock_redis.hgetall.return_value = {}  # Empty data
        events = []
        async for event in storage.export_all():
            events.append(event)
        assert events == []


# ==========================================================================
# storage/backends/redis/saga.py  – 469-471, 475
