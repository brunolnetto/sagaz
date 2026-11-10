"""End-to-end DLQ lifecycle coverage with SQLite and a real RabbitMQ broker."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_dlq_event_is_replayed_after_rabbitmq_recovers(rabbitmq_container, tmp_path) -> None:
    """A failed delivery reaches DLQ, then the same event is delivered once."""
    aio_pika = pytest.importorskip("aio_pika")
    pytest.importorskip("aiosqlite")

    from sagaz.core.outbox.brokers.base import BrokerPublishError
    from sagaz.core.outbox.brokers.rabbitmq import (
        RabbitMQBroker,
        RabbitMQBrokerConfig,
    )
    from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
    from sagaz.core.outbox.worker import OutboxWorker
    from sagaz.core.storage.backends.sqlite import SQLiteOutboxStorage

    amqp_url = rabbitmq_container.get_connection_url()
    exchange_name = f"sagaz.dlq.{uuid4().hex}"
    queue_name = f"sagaz-dlq-{uuid4().hex}"
    routing_key = "OrderCreated"

    class FailOnceRabbitMQBroker(RabbitMQBroker):
        """Fail before publishing once, then delegate to the real RabbitMQ broker."""

        def __init__(self, config: RabbitMQBrokerConfig) -> None:
            super().__init__(config)
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

            await super().publish(
                topic=topic,
                message=message,
                headers=headers,
                key=key,
            )

    broker = FailOnceRabbitMQBroker(
        RabbitMQBrokerConfig(
            url=amqp_url,
            exchange_name=exchange_name,
            exchange_type="topic",
            exchange_durable=False,
            connection_timeout=60.0,
        )
    )
    consumer_connection = None
    storage = SQLiteOutboxStorage(str(tmp_path / "dlq-outbox.sqlite"))

    try:
        await broker.connect()

        # Bind a real RabbitMQ queue before processing so both absence after the
        # injected failure and exactly-once delivery after replay are observable.
        consumer_connection = await aio_pika.connect_robust(amqp_url)
        consumer_channel = await consumer_connection.channel()
        exchange = await consumer_channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=False,
        )
        queue = await consumer_channel.declare_queue(
            queue_name,
            durable=False,
            auto_delete=True,
        )
        await queue.bind(exchange, routing_key=routing_key)

        await storage.initialize()
        event = OutboxEvent(
            saga_id="saga-dlq-recovery",
            event_type=routing_key,
            payload={"order_id": "order-123", "amount": 42.50},
        )
        await storage.insert(event)

        worker = OutboxWorker(
            storage=storage,
            broker=broker,
            config=OutboxConfig(batch_size=1, max_retries=1),
            worker_id="dlq-lifecycle-test",
        )

        # First publish fails before reaching RabbitMQ and exhausts max_retries.
        await worker.process_batch()

        dead_lettered = await storage.get_by_id(event.event_id)
        assert dead_lettered is not None
        assert dead_lettered.status == OutboxStatus.DEAD_LETTER
        assert dead_lettered.retry_count == 1
        assert dead_lettered.dead_letter_at is not None
        assert dead_lettered.dead_letter_reason == "temporary broker outage"
        assert await storage.get_dead_letter_events() == [dead_lettered]
        assert await queue.get(timeout=0.2, fail=False) is None

        # Operator replay moves the same persistent SQLite row back to PENDING.
        replayed = await storage.requeue_dead_letter_event(event.event_id)
        assert replayed.event_id == event.event_id
        assert replayed.status == OutboxStatus.PENDING
        assert replayed.retry_count == 0
        assert replayed.replay_count == 1
        assert replayed.dead_letter_at is None
        assert replayed.dead_letter_reason is None
        assert await storage.get_dead_letter_events() == []

        # The same worker retries against the real RabbitMQ broker.
        processed = await worker.process_batch()

        assert processed == 1
        delivered = await storage.get_by_id(event.event_id)
        assert delivered is not None
        assert delivered.status == OutboxStatus.SENT
        assert delivered.replay_count == 1
        assert delivered.dead_letter_at is None
        assert delivered.dead_letter_reason is None
        assert broker.publish_attempts == 2

        message = await queue.get(timeout=5.0, fail=True)
        assert message is not None
        async with message.process():
            assert message.routing_key == routing_key
            assert message.headers["event_id"] == event.event_id
            payload = json.loads(message.body)
            assert payload["event_id"] == event.event_id
            assert payload["saga_id"] == event.saga_id
            assert payload["event_type"] == event.event_type
            assert payload["payload"] == event.payload

        # One injected failure plus one successful publish means one broker message.
        assert await queue.get(timeout=0.2, fail=False) is None
    finally:
        await storage.close()
        await broker.close()
        if consumer_connection is not None:
            await consumer_connection.close()
