"""``RedisOutboxStorage.get_pending_count`` counts PENDING events only.

It used to return XLEN of the stream, which keeps every delivered (claimed,
sent, dead-lettered) entry until MAXLEN trims it. The unit tests mock Redis;
the ``integration`` tests run against a real Redis container.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

PREFIX = "test:pending"


def _storage(groups: list[dict]) -> tuple[RedisOutboxStorage, AsyncMock]:
    storage = RedisOutboxStorage("redis://localhost", prefix=PREFIX, consumer_group="workers")
    storage._initialized = True
    redis = AsyncMock()
    redis.xlen = AsyncMock(return_value=999)
    redis.xinfo_groups = AsyncMock(return_value=groups)
    redis.xrange = AsyncMock(return_value=[])
    storage._redis = redis
    return storage, redis


class TestPendingCountUnit:
    async def test_uses_consumer_group_lag_not_stream_length(self):
        storage, redis = _storage([{"name": b"workers", "lag": 3, "last-delivered-id": b"9-0"}])

        assert await storage.get_pending_count() == 3
        redis.xlen.assert_not_awaited()

    async def test_counts_undelivered_entries_when_lag_is_unknown(self, monkeypatch):
        from sagaz.core.storage.backends.redis import _outbox_pending

        monkeypatch.setattr(_outbox_pending, "_UNDELIVERED_PAGE_SIZE", 2)
        # Redis 6 has no "lag"; Redis 7 reports None after XDEL.
        storage, redis = _storage([{"name": "workers", "last-delivered-id": b"4-0", "lag": None}])
        redis.xrange = AsyncMock(
            side_effect=[[(b"5-0", {}), (b"6-0", {})], [(b"7-0", {})]],
        )

        assert await storage.get_pending_count() == 3
        starts = [call.kwargs["min"] for call in redis.xrange.await_args_list]
        assert starts == ["(4-0", "(6-0"]

    async def test_missing_group_counts_zero(self):
        storage, _ = _storage([{"name": b"someone-else", "lag": 10}])

        assert await storage.get_pending_count() == 0

    async def test_redis_error_counts_zero(self):
        storage, redis = _storage([])
        redis.xinfo_groups = AsyncMock(side_effect=Exception("no such key"))

        assert await storage.get_pending_count() == 0


# ---------------------------------------------------------------------------
# Real Redis
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis_storage(request):
    redis_url = request.getfixturevalue("redis_url")
    if not redis_url:
        pytest.skip("Redis container not available")

    import redis.asyncio as redis

    # Flush before initialize(), which creates the consumer group.
    client = redis.from_url(redis_url)
    await client.flushdb()
    await client.aclose()

    storage = RedisOutboxStorage(redis_url=redis_url, prefix=PREFIX, consumer_group="pending")
    await storage.initialize()
    yield storage
    await storage.close()


async def _insert(storage: RedisOutboxStorage, count: int) -> list[str]:
    ids = []
    for _ in range(count):
        event = OutboxEvent(
            event_id=f"evt-{uuid4().hex[:8]}",
            saga_id="saga-1",
            event_type="test.event",
            payload={},
            created_at=datetime.now(UTC),
        )
        await storage.insert(event)
        ids.append(event.event_id)
    return ids


@pytest.mark.integration
class TestPendingCountRealRedis:
    async def test_empty_outbox(self, redis_storage):
        assert await redis_storage.get_pending_count() == 0

    async def test_claimed_and_sent_events_are_not_pending(self, redis_storage):
        await _insert(redis_storage, 5)
        assert await redis_storage.get_pending_count() == 5

        claimed = await redis_storage.claim_batch("worker-1", batch_size=3)
        assert len(claimed) == 3
        await redis_storage.update_status(claimed[0].event_id, OutboxStatus.SENT)

        assert await redis_storage.get_pending_count() == 2
        stats = await redis_storage.get_statistics()
        assert stats.pending_records == 2

    async def test_requeued_dead_letter_is_pending_again(self, redis_storage):
        (event_id,) = await _insert(redis_storage, 1)
        await redis_storage.claim_batch("worker-1", batch_size=1)
        await redis_storage.update_status(event_id, OutboxStatus.DEAD_LETTER, "broker down")
        assert await redis_storage.get_pending_count() == 0

        await redis_storage.requeue_dead_letter_event(event_id)

        assert await redis_storage.get_pending_count() == 1

    async def test_fallback_matches_lag(self, redis_storage):
        await _insert(redis_storage, 4)
        await redis_storage.claim_batch("worker-1", batch_size=1)
        group = await redis_storage._consumer_group_info()
        assert group is not None

        counted = await redis_storage._count_entries_after(
            redis_storage._text(group["last-delivered-id"])
        )

        assert counted == group["lag"] == 3
