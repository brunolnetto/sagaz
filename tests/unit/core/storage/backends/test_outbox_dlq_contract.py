"""Dead-letter queue contract shared by every outbox storage backend.

The same scenarios run against the in-memory, SQLite, Redis and PostgreSQL
backends so that DLQ semantics (reason/timestamp handling, listing, requeue,
replay-loop guard and purge) cannot drift between them. Redis and PostgreSQL
use testcontainers and are skipped when Docker is unavailable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus, ReplayLoopError

BACKENDS = [
    "memory",
    "sqlite",
    pytest.param("redis", marks=pytest.mark.integration),
    pytest.param("postgresql", marks=pytest.mark.integration),
]


async def _memory(request, tmp_path):
    from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

    return InMemoryOutboxStorage()


async def _sqlite(request, tmp_path):
    from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

    return SQLiteOutboxStorage(db_path=str(tmp_path / "outbox.db"))


async def _redis(request, tmp_path):
    redis_url = request.getfixturevalue("redis_url")
    if not redis_url:
        pytest.skip("Redis container not available")

    import redis.asyncio as redis

    from sagaz.core.storage.backends.redis import RedisOutboxStorage

    # Flush before initialize(): it creates the consumer group, and a second
    # initialize() is a no-op, so flushing afterwards would break claiming.
    client = redis.from_url(redis_url)
    await client.flushdb()
    await client.aclose()
    return RedisOutboxStorage(redis_url=redis_url, prefix="test:dlq", consumer_group="dlq")


async def _postgresql(request, tmp_path):
    dsn = request.getfixturevalue("postgres_connection_string")
    if not dsn:
        pytest.skip("PostgreSQL container not available")

    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    return PostgreSQLOutboxStorage(connection_string=dsn, pool_min_size=1, pool_max_size=2)


FACTORIES = {"memory": _memory, "sqlite": _sqlite, "redis": _redis, "postgresql": _postgresql}


@pytest.fixture(params=BACKENDS)
async def storage(request, tmp_path):
    storage = await FACTORIES[request.param](request, tmp_path)
    initialize = getattr(storage, "initialize", None)
    if callable(initialize):
        await initialize()
    if request.param == "postgresql":
        # The container is session-scoped; start every test from an empty table.
        async with storage._pool.acquire() as conn:
            await conn.execute("TRUNCATE saga_outbox")
    yield storage
    close = getattr(storage, "close", None)
    if callable(close):
        await close()


async def _insert(storage, **fields) -> OutboxEvent:
    return await storage.insert(
        OutboxEvent(saga_id="saga-1", event_type="Evt", payload={"n": 1}, **fields)
    )


async def _dead_letter(storage, *, reason="boom", at: datetime | None = None) -> OutboxEvent:
    event = await _insert(storage)
    event.dead_letter_at = at
    event.dead_letter_reason = reason
    return await storage.update_status(
        event.event_id, OutboxStatus.DEAD_LETTER, error_message=reason, event=event
    )


class TestStatusTransitions:
    async def test_failed_with_error_increments_retry_and_records_error(self, storage):
        event = await _insert(storage)
        await storage.update_status(event.event_id, OutboxStatus.FAILED, error_message="e1")
        updated = await storage.update_status(
            event.event_id, OutboxStatus.FAILED, error_message="e2"
        )
        assert updated.retry_count == 2
        assert updated.last_error == "e2"

    async def test_failed_without_error_still_counts_as_retry(self, storage):
        event = await _insert(storage)
        updated = await storage.update_status(event.event_id, OutboxStatus.FAILED)
        assert updated.retry_count == 1

    async def test_dead_letter_from_error_message_only(self, storage):
        event = await _insert(storage)
        updated = await storage.update_status(
            event.event_id, OutboxStatus.DEAD_LETTER, error_message="max_retries_exceeded"
        )
        assert updated.status == OutboxStatus.DEAD_LETTER
        assert updated.dead_letter_reason == "max_retries_exceeded"
        assert updated.dead_letter_at is not None

    async def test_dead_letter_event_reason_wins_and_timestamp_is_kept(self, storage):
        at = datetime(2026, 1, 1, tzinfo=UTC)
        event = await _insert(storage)
        event.dead_letter_reason = "poison message"
        event.dead_letter_at = at
        updated = await storage.update_status(
            event.event_id, OutboxStatus.DEAD_LETTER, error_message="other", event=event
        )
        assert updated.dead_letter_reason == "poison message"
        assert updated.dead_letter_at == at

    async def test_dead_letter_event_without_timestamp_defaults_to_now(self, storage):
        """Matches COALESCE(dead_letter_at, NOW()) in the PostgreSQL/SQLite backends."""
        before = datetime.now(UTC)
        updated = await _dead_letter(storage, at=None)
        assert updated.dead_letter_at is not None
        assert updated.dead_letter_at >= before


class TestDeadLetterListing:
    async def test_only_dead_letter_events_are_listed(self, storage):
        dead = await _dead_letter(storage)
        await _insert(storage)
        listed = await storage.get_dead_letter_events()
        assert [e.event_id for e in listed] == [dead.event_id]

    async def test_limit_is_respected(self, storage):
        for _ in range(3):
            await _dead_letter(storage)
        assert len(await storage.get_dead_letter_events(limit=2)) == 2


class TestRequeue:
    async def test_requeue_resets_event_and_makes_it_claimable(self, storage):
        dead = await _dead_letter(storage)

        requeued = await storage.requeue_dead_letter_event(dead.event_id)

        assert requeued.status == OutboxStatus.PENDING
        assert requeued.replay_count == 1
        assert requeued.retry_count == 0
        assert requeued.dead_letter_at is None
        assert not requeued.dead_letter_reason
        assert await storage.get_dead_letter_events() == []
        claimed = await storage.claim_batch("worker-1", batch_size=10)
        assert dead.event_id in {e.event_id for e in claimed}

    async def test_missing_event_raises_key_error(self, storage):
        with pytest.raises(KeyError, match="not found"):
            await storage.requeue_dead_letter_event(str(uuid4()))

    async def test_replay_loop_is_blocked_unless_forced(self, storage):
        dead = await _dead_letter(storage)
        for _ in range(3):
            await storage.requeue_dead_letter_event(dead.event_id)
            await storage.update_status(dead.event_id, OutboxStatus.DEAD_LETTER, "again")

        with pytest.raises(ReplayLoopError):
            await storage.requeue_dead_letter_event(dead.event_id)

        forced = await storage.requeue_dead_letter_event(dead.event_id, force=True)
        assert forced.replay_count == 4


class TestPurge:
    async def test_purge_all_removes_only_dead_letter_events(self, storage):
        await _dead_letter(storage)
        await _dead_letter(storage)
        alive = await _insert(storage)

        assert await storage.purge_dead_letter_events() == 2
        assert await storage.get_dead_letter_events() == []
        assert await storage.get_by_id(alive.event_id) is not None

    async def test_purge_older_than_keeps_recent_events(self, storage):
        old = await _dead_letter(storage, at=datetime.now(UTC) - timedelta(days=10))
        recent = await _dead_letter(storage, at=datetime.now(UTC))

        assert await storage.purge_dead_letter_events(older_than=timedelta(days=7)) == 1
        assert await storage.get_by_id(old.event_id) is None
        assert await storage.get_by_id(recent.event_id) is not None

    async def test_purge_with_empty_queue_returns_zero(self, storage):
        await _insert(storage)
        assert await storage.purge_dead_letter_events(older_than=timedelta(days=1)) == 0
