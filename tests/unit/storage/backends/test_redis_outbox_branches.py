
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.storage.backends.redis.outbox import OutboxEvent, OutboxStatus, RedisOutboxStorage


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
        partition_key=None
    )

    # Force aggregate_id to None to test the fallback, bypassing __post_init__ logic
    event.aggregate_id = None

    data = storage._serialize_event(event)
    assert data["aggregate_type"] == "saga" # Default
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
    storage.get_by_id = AsyncMock(return_value=OutboxEvent(
        event_id="evt-1", saga_id="s-1", event_type="t", payload={}, status=OutboxStatus.PENDING, created_at=datetime.now(UTC)
    ))

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

