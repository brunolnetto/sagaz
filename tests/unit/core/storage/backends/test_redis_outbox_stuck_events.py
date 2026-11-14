"""Stuck-event detection and release for ``RedisOutboxStorage``.

XPENDING reports *stream message ids*, which differ from outbox event ids; the
storage must map them back through the processing hash. The unit tests below
mock Redis; the ``integration`` tests run the same flow against a real Redis
container.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage

PREFIX = "test:stuck"
STREAM_KEY = f"{PREFIX}:events"
PROCESSING_KEY = f"{PREFIX}:processing"


def _event(event_id: str, status: OutboxStatus = OutboxStatus.CLAIMED) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        saga_id="saga-1",
        event_type="test.event",
        payload={},
        status=status,
        created_at=datetime.now(UTC),
    )


def _pipeline(status: bytes | None = b"claimed", execute_error: Exception | None = None):
    pipe = MagicMock()
    pipe.watch = AsyncMock()
    pipe.unwatch = AsyncMock()
    pipe.hget = AsyncMock(return_value=status)
    pipe.execute = AsyncMock(side_effect=execute_error)
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    return pipe


def _storage(
    pending: list[dict],
    processing: dict[bytes, bytes],
    events: dict[str, OutboxEvent],
    pipe: MagicMock | None = None,
) -> tuple[RedisOutboxStorage, AsyncMock]:
    storage = RedisOutboxStorage("redis://localhost", prefix=PREFIX)
    storage._initialized = True
    redis = AsyncMock()
    redis.xpending_range = AsyncMock(return_value=pending)
    redis.hgetall = AsyncMock(side_effect=lambda key: processing if key == PROCESSING_KEY else {})
    redis.pipeline = MagicMock(return_value=pipe or _pipeline())
    storage._redis = redis
    storage.get_by_id = AsyncMock(side_effect=lambda event_id: events.get(event_id))
    return storage, redis


class TestGetStuckEventsUnit:
    async def test_maps_stream_message_id_to_event_id(self):
        """Regression: the stream message id used to be looked up as an event id."""
        storage, _ = _storage(
            pending=[{"message_id": b"1700000000000-0", "time_since_delivered": 400_000}],
            processing={b"evt-1": b"1700000000000-0"},
            events={"evt-1": _event("evt-1")},
        )

        stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

        assert [e.event_id for e in stuck] == ["evt-1"]

    async def test_threshold_is_passed_to_redis_and_clamped_at_zero(self):
        storage, redis = _storage(pending=[], processing={}, events={})

        await storage.get_stuck_events(claimed_older_than_seconds=1.5)
        assert redis.xpending_range.await_args.kwargs["idle"] == 1500

        # Redis rejects a negative IDLE ("ERR ... min idle time"); clamp it.
        await storage.get_stuck_events(claimed_older_than_seconds=-10)
        assert redis.xpending_range.await_args.kwargs["idle"] == 0

    async def test_skips_unmapped_and_non_claimed_entries(self):
        storage, _ = _storage(
            pending=[
                {"message_id": b"1-0"},  # not in the processing hash
                {"message_id": b"2-0"},  # event already sent
                {"message_id": b"3-0"},  # metadata expired
                {"message_id": b"4-0"},  # genuinely stuck
            ],
            processing={b"evt-2": b"2-0", b"evt-3": b"3-0", b"evt-4": b"4-0"},
            events={"evt-2": _event("evt-2", OutboxStatus.SENT), "evt-4": _event("evt-4")},
        )

        stuck = await storage.get_stuck_events(claimed_older_than_seconds=1)

        assert [e.event_id for e in stuck] == ["evt-4"]

    async def test_pages_through_the_pending_list(self, monkeypatch):
        from sagaz.core.storage.backends.redis import _outbox_claiming

        monkeypatch.setattr(_outbox_claiming, "_PENDING_PAGE_SIZE", 2)
        storage, redis = _storage(
            pending=[],
            processing={b"evt-3": b"3-0"},
            events={"evt-3": _event("evt-3")},
        )
        redis.xpending_range = AsyncMock(
            side_effect=[
                [{"message_id": b"1-0"}, {"message_id": b"2-0"}],
                [{"message_id": b"3-0"}],
            ]
        )

        stuck = await storage.get_stuck_events(claimed_older_than_seconds=1)

        assert [e.event_id for e in stuck] == ["evt-3"]
        starts = [call.kwargs["min"] for call in redis.xpending_range.await_args_list]
        assert starts == ["-", "(2-0"]

    async def test_redis_error_returns_empty(self):
        storage, redis = _storage(pending=[], processing={}, events={})
        redis.xpending_range = AsyncMock(side_effect=Exception("boom"))

        assert await storage.get_stuck_events() == []


class TestReleaseStuckEventsUnit:
    async def test_requeues_stuck_claim(self):
        pipe = _pipeline()
        storage, _ = _storage(
            pending=[{"message_id": b"1700000000000-0"}],
            processing={b"evt-1": b"1700000000000-0"},
            events={"evt-1": _event("evt-1")},
            pipe=pipe,
        )

        released = await storage.release_stuck_events(claimed_older_than_seconds=300)

        assert released == 1
        pipe.xack.assert_called_once_with(STREAM_KEY, "sagaz-workers", "1700000000000-0")
        pipe.hdel.assert_called_once_with(PROCESSING_KEY, "evt-1")
        mapping = pipe.hset.call_args.kwargs["mapping"]
        assert mapping == {"status": "pending", "claimed_at": "", "worker_id": ""}
        assert pipe.xadd.call_args.args[1]["event_id"] == "evt-1"
        pipe.execute.assert_awaited_once()

    async def test_skips_claim_completed_concurrently(self):
        pipe = _pipeline(status=b"sent")
        storage, _ = _storage(
            pending=[{"message_id": b"1-0"}],
            processing={b"evt-1": b"1-0"},
            events={"evt-1": _event("evt-1")},
            pipe=pipe,
        )

        assert await storage.release_stuck_events(claimed_older_than_seconds=1) == 0
        pipe.unwatch.assert_awaited_once()
        pipe.execute.assert_not_awaited()

    async def test_watch_error_is_not_counted(self):
        from redis.exceptions import WatchError

        storage, _ = _storage(
            pending=[{"message_id": b"1-0"}],
            processing={b"evt-1": b"1-0"},
            events={"evt-1": _event("evt-1")},
            pipe=_pipeline(execute_error=WatchError()),
        )

        assert await storage.release_stuck_events(claimed_older_than_seconds=1) == 0

    async def test_failure_is_logged_and_skipped(self):
        storage, _ = _storage(
            pending=[{"message_id": b"1-0"}],
            processing={b"evt-1": b"1-0"},
            events={"evt-1": _event("evt-1")},
            pipe=_pipeline(execute_error=RuntimeError("connection lost")),
        )

        assert await storage.release_stuck_events(claimed_older_than_seconds=1) == 0


class TestUpdateStatusAcksDelivery:
    async def test_terminal_status_acks_stream_message(self):
        storage, redis = _storage(pending=[], processing={}, events={})
        storage.get_by_id = AsyncMock(return_value=_event("evt-1", OutboxStatus.SENT))
        redis.hget = AsyncMock(return_value=b"1-0")

        await storage.update_status("evt-1", OutboxStatus.SENT)

        redis.xack.assert_awaited_once_with(STREAM_KEY, "sagaz-workers", b"1-0")
        redis.hdel.assert_awaited_once_with(PROCESSING_KEY, "evt-1")

    async def test_terminal_status_without_delivery_skips_ack(self):
        storage, redis = _storage(pending=[], processing={}, events={})
        storage.get_by_id = AsyncMock(return_value=_event("evt-1", OutboxStatus.SENT))
        redis.hget = AsyncMock(return_value=None)

        await storage.update_status("evt-1", OutboxStatus.SENT)

        redis.xack.assert_not_awaited()


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

    storage = RedisOutboxStorage(redis_url=redis_url, prefix=PREFIX, consumer_group="stuck")
    await storage.initialize()
    yield storage
    await storage.close()


async def _insert(storage: RedisOutboxStorage, count: int) -> list[str]:
    ids = []
    for _ in range(count):
        event = _event(f"evt-{uuid4().hex[:8]}", OutboxStatus.PENDING)
        await storage.insert(event)
        ids.append(event.event_id)
    return ids


@pytest.mark.integration
class TestStuckEventsRealRedis:
    async def test_get_stuck_events_returns_old_claims(self, redis_storage):
        ids = await _insert(redis_storage, 2)
        claimed = await redis_storage.claim_batch("worker-1", batch_size=10)
        assert sorted(e.event_id for e in claimed) == sorted(ids)

        await asyncio.sleep(0.3)

        stuck = await redis_storage.get_stuck_events(claimed_older_than_seconds=0.1)
        assert sorted(e.event_id for e in stuck) == sorted(ids)
        assert all(e.status == OutboxStatus.CLAIMED for e in stuck)
        assert await redis_storage.get_stuck_events(claimed_older_than_seconds=300) == []

    async def test_negative_threshold_is_accepted(self, redis_storage):
        ids = await _insert(redis_storage, 1)
        await redis_storage.claim_batch("worker-1", batch_size=10)

        stuck = await redis_storage.get_stuck_events(claimed_older_than_seconds=-1)

        assert [e.event_id for e in stuck] == ids

    async def test_finished_events_are_not_stuck(self, redis_storage):
        sent_id, stuck_id = await _insert(redis_storage, 2)
        await redis_storage.claim_batch("worker-1", batch_size=10)
        await redis_storage.update_status(sent_id, OutboxStatus.SENT)

        stuck = await redis_storage.get_stuck_events(claimed_older_than_seconds=0)

        assert [e.event_id for e in stuck] == [stuck_id]

    async def test_release_makes_event_claimable_again(self, redis_storage):
        (event_id,) = await _insert(redis_storage, 1)
        await redis_storage.claim_batch("crashed-worker", batch_size=10)
        await asyncio.sleep(0.3)

        released = await redis_storage.release_stuck_events(claimed_older_than_seconds=0.1)

        assert released == 1
        event = await redis_storage.get_by_id(event_id)
        assert event is not None
        assert event.status == OutboxStatus.PENDING
        assert event.claimed_at is None
        assert event.worker_id is None
        assert await redis_storage.get_stuck_events(claimed_older_than_seconds=0) == []

        reclaimed = await redis_storage.claim_batch("worker-2", batch_size=10)
        assert [e.event_id for e in reclaimed] == [event_id]
        assert reclaimed[0].worker_id == "worker-2"
