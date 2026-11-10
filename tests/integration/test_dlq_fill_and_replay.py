"""End-to-end DLQ lifecycle coverage using in-memory infrastructure."""

from __future__ import annotations

import json

import pytest

from sagaz.core.outbox.brokers.base import BrokerPublishError
from sagaz.core.outbox.brokers.memory import InMemoryBroker
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage


class FailOnceInMemoryBroker(InMemoryBroker):
    """Fail the first publish, then behave like the normal in-memory broker."""

    def __init__(self) -> None:
        super().__init__()
        self.publish_attempts = 0

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        self.publish_attempts += 1
        if self.publish_attempts == 1:
            raise BrokerPublishError("temporary broker outage")

        await super().publish(topic=topic, message=message, headers=headers, key=key)


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_dlq_event_is_replayed_after_broker_recovers() -> None:
    """A failed publish reaches DLQ and the same event is later delivered once."""
    storage = InMemoryOutboxStorage()
    broker = FailOnceInMemoryBroker()
    await broker.connect()

    event = OutboxEvent(
        saga_id="saga-dlq-recovery",
        event_type="OrderCreated",
        payload={"order_id": "order-123", "amount": 42.50},
    )
    await storage.insert(event)

    worker = OutboxWorker(
        storage=storage,
        broker=broker,
        config=OutboxConfig(batch_size=1, max_retries=1),
        worker_id="dlq-lifecycle-test",
    )

    # The first broker failure exhausts the configured retry budget.
    await worker.process_batch()

    dead_lettered = await storage.get_by_id(event.event_id)
    assert dead_lettered is not None
    assert dead_lettered.status == OutboxStatus.DEAD_LETTER
    assert dead_lettered.retry_count == 1
    assert dead_lettered.dead_letter_at is not None
    assert dead_lettered.dead_letter_reason == "temporary broker outage"
    assert await storage.get_dead_letter_events() == [dead_lettered]
    assert broker.get_messages("OrderCreated") == []

    # Operator replay moves the same event back to PENDING and clears DLQ fields.
    replayed = await storage.requeue_dead_letter_event(event.event_id)
    assert replayed.event_id == event.event_id
    assert replayed.status == OutboxStatus.PENDING
    assert replayed.retry_count == 0
    assert replayed.replay_count == 1
    assert replayed.dead_letter_at is None
    assert replayed.dead_letter_reason is None
    assert await storage.get_dead_letter_events() == []

    # The broker is now healthy. The same worker publishes the replayed event.
    processed = await worker.process_batch()

    assert processed == 1
    delivered = await storage.get_by_id(event.event_id)
    assert delivered is not None
    assert delivered.status == OutboxStatus.SENT
    assert delivered.replay_count == 1
    assert delivered.dead_letter_at is None
    assert delivered.dead_letter_reason is None
    assert broker.publish_attempts == 2

    messages = broker.get_messages("OrderCreated")
    assert len(messages) == 1
    message = messages[0]
    assert message["headers"]["event_id"] == event.event_id
    payload = json.loads(message["message"])
    assert payload["event_id"] == event.event_id
    assert payload["saga_id"] == event.saga_id
    assert payload["event_type"] == event.event_type
    assert payload["payload"] == event.payload
