"""Redis outbox: an event returned to PENDING is delivered again (#401).

``claim_batch`` reads only stream entries not yet delivered to the consumer
group, so moving an event back to PENDING must add a fresh entry. Before the
fix, an event whose publish failed once stayed PENDING forever on Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage
from tests.unit.core.storage.backends._fake_redis import fake_redis_outbox


def _event(event_id: str = "evt-1") -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        saga_id="saga-1",
        event_type="order.created",
        payload={"n": 1},
        created_at=datetime.now(UTC),
    )


class FlakyBroker(InMemoryBroker):
    """Fails the first ``failures`` publishes, then publishes normally."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def publish_event(self, event):
        if self.failures:
            self.failures -= 1
            msg = "broker unavailable"
            raise ConnectionError(msg)
        return await super().publish_event(event)


async def _retry_scenario(storage: RedisOutboxStorage) -> None:
    await storage.insert(_event())
    broker = FlakyBroker(failures=1)
    await broker.connect()
    worker = OutboxWorker(storage, broker, OutboxConfig(batch_size=10, max_retries=3))

    await worker.process_batch()  # publish fails, event goes back to PENDING
    failed_once = await storage.get_by_id("evt-1")
    assert failed_once.status == OutboxStatus.PENDING
    assert await storage.get_pending_count() == 1  # deliverable again

    await worker.process_batch()  # redelivered and published

    sent = await storage.get_by_id("evt-1")
    assert sent.status == OutboxStatus.SENT
    assert sent.retry_count == 1
    assert sum(len(m) for m in broker._messages.values()) == 1
    assert await storage.get_pending_count() == 0


async def _exhausted_retries_reach_the_dlq(storage: RedisOutboxStorage) -> None:
    await storage.insert(_event("evt-2"))
    broker = FlakyBroker(failures=10)
    await broker.connect()
    worker = OutboxWorker(storage, broker, OutboxConfig(batch_size=10, max_retries=2))

    for _ in range(5):
        await worker.process_batch()

    event = await storage.get_by_id("evt-2")
    assert event.status == OutboxStatus.DEAD_LETTER
    assert await storage.get_pending_count() == 0


async def _requeue_adds_exactly_one_delivery(storage: RedisOutboxStorage) -> None:
    await storage.insert(_event("evt-3"))
    await storage.claim_batch("w", 10)
    await storage.update_status("evt-3", OutboxStatus.DEAD_LETTER)

    await storage.requeue_dead_letter_event("evt-3")
    assert await storage.get_pending_count() == 1
    claimed = await storage.claim_batch("w", 10)
    assert [e.event_id for e in claimed] == ["evt-3"]
    assert await storage.claim_batch("w", 10) == []  # no duplicate entry


async def _pending_to_pending_adds_nothing(storage: RedisOutboxStorage) -> None:
    await storage.insert(_event("evt-4"))
    await storage.update_status("evt-4", OutboxStatus.PENDING)
    assert await storage.get_pending_count() == 1


SCENARIOS = [
    _retry_scenario,
    _exhausted_retries_reach_the_dlq,
    _requeue_adds_exactly_one_delivery,
    _pending_to_pending_adds_nothing,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__.strip("_"))
async def test_with_fake_redis(scenario):
    await scenario(await fake_redis_outbox())


@pytest.fixture
async def redis_storage(request):
    redis_url = request.getfixturevalue("redis_url")
    if not redis_url:
        pytest.skip("Redis container not available")

    import redis.asyncio as redis

    client = redis.from_url(redis_url)
    await client.flushdb()
    await client.aclose()

    storage = RedisOutboxStorage(redis_url=redis_url, prefix="retry", consumer_group="retry")
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.mark.integration
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.__name__.strip("_"))
async def test_with_real_redis(redis_storage, scenario):
    await scenario(redis_storage)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), (b"pending", OutboxStatus.PENDING), ("sent", OutboxStatus.SENT), (b"??", None)],
)
def test_decode_status(raw, expected):
    assert RedisOutboxStorage._decode_status(raw) == expected
