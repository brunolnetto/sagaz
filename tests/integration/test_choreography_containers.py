"""
Integration tests for choreography EventBus backends using real broker containers.

Each test class exercises a concrete ``AbstractEventBus`` implementation against
a live broker started by testcontainers.  Tests are skipped automatically when:

- Docker / testcontainers is not available.
- The required optional package (aiokafka / aio-pika / redis) is missing.
- ``--no-containers`` CLI flag or ``SAGAZ_NO_CONTAINERS=1`` env var is set.

Run only these tests:
    pytest tests/integration/test_choreography_containers.py -v -m integration

Run with containers pre-started in parallel (faster for full suite):
    pytest tests/integration/test_choreography_containers.py -v -m integration \\
        --parallel-containers
"""

from __future__ import annotations

import asyncio

import pytest

from sagaz.choreography.events import AbstractEventBus, Event

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 10.0  # seconds — generous enough for slow CI runners


async def _wait_for(condition, timeout: float = _TIMEOUT, poll: float = 0.05) -> bool:
    """Poll *condition()* until True or *timeout* expires.  Returns True on success."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(poll)
    return False


# ---------------------------------------------------------------------------
# Redis Streams EventBus
# ---------------------------------------------------------------------------


@pytest.mark.xdist_group(name="containers")
class TestRedisStreamsEventBusIntegration:
    """Integration tests for RedisStreamsEventBus against a live Redis container."""

    @pytest.mark.asyncio
    async def test_publish_subscribe_round_trip(self, redis_container) -> None:
        """A published event must be received by a subscribed handler."""
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        config = RedisStreamsBusConfig(
            url=f"redis://{host}:{port}",
            stream_name="test.choreography.rtt",
            consumer_group="test-rtt",
            consumer_name="worker-1",
            block_timeout_ms=200,
        )
        bus = RedisStreamsEventBus(config)
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        try:
            await bus.start()
            bus.subscribe("order.created", handler)
            await bus.publish(Event("order.created", {"order_id": "ORD-1"}))

            assert await _wait_for(lambda: len(received) >= 1), (
                "Handler was not called within timeout"
            )
        finally:
            await bus.stop()

        assert len(received) == 1
        assert received[0].event_type == "order.created"
        assert received[0].data["order_id"] == "ORD-1"

    @pytest.mark.asyncio
    async def test_wildcard_handler_receives_all_event_types(self, redis_container) -> None:
        """A ``*`` handler must receive events of any type."""
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        config = RedisStreamsBusConfig(
            url=f"redis://{host}:{port}",
            stream_name="test.choreography.wildcard",
            consumer_group="test-wildcard",
            consumer_name="worker-1",
            block_timeout_ms=200,
        )
        bus = RedisStreamsEventBus(config)
        received_types: list[str] = []

        bus_started = False
        try:
            await bus.start()
            bus_started = True
            bus.subscribe("*", lambda e: received_types.append(e.event_type))

            await bus.publish(Event("alpha.event"))
            await bus.publish(Event("beta.event"))

            assert await _wait_for(lambda: len(received_types) >= 2)
        finally:
            if bus_started:
                await bus.stop()

        assert "alpha.event" in received_types
        assert "beta.event" in received_types

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self, redis_container) -> None:
        """Unsubscribed handler must not receive events published after unsubscription."""
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        config = RedisStreamsBusConfig(
            url=f"redis://{host}:{port}",
            stream_name="test.choreography.unsub",
            consumer_group="test-unsub",
            consumer_name="worker-1",
            block_timeout_ms=200,
        )
        bus = RedisStreamsEventBus(config)
        calls = 0

        async def handler(e: Event) -> None:
            nonlocal calls
            calls += 1

        try:
            await bus.start()
            bus.subscribe("x.event", handler)
            await bus.publish(Event("x.event"))
            assert await _wait_for(lambda: calls >= 1)

            bus.unsubscribe("x.event", handler)
            before = calls
            await bus.publish(Event("x.event"))
            await asyncio.sleep(0.5)  # allow any in-flight delivery
        finally:
            await bus.stop()

        assert calls == before, "Handler received event after unsubscription"

    @pytest.mark.asyncio
    async def test_start_idempotent(self, redis_container) -> None:
        """Calling start() twice must not raise or create duplicate reader tasks."""
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        config = RedisStreamsBusConfig(
            url=f"redis://{host}:{port}",
            stream_name="test.choreography.idem",
            consumer_group="test-idem",
            consumer_name="worker-1",
            block_timeout_ms=200,
        )
        bus = RedisStreamsEventBus(config)
        try:
            await bus.start()
            first_task = bus._reader_task
            await bus.start()  # must be a no-op
            assert bus._reader_task is first_task
        finally:
            await bus.stop()


# ---------------------------------------------------------------------------
# Kafka EventBus
# ---------------------------------------------------------------------------


@pytest.mark.xdist_group(name="containers")
class TestKafkaEventBusIntegration:
    """Integration tests for KafkaEventBus against a live Kafka container."""

    @pytest.mark.asyncio
    async def test_publish_subscribe_round_trip(self, kafka_container) -> None:
        """A published event must be received by a subscribed handler."""
        from sagaz.choreography.buses.kafka import (
            KafkaEventBus,
            KafkaEventBusConfig,
        )

        bootstrap = kafka_container.get_bootstrap_server()
        config = KafkaEventBusConfig(
            bootstrap_servers=bootstrap,
            topic="test.choreography",
            consumer_group="test-cg-rtt",
            consumer_name="worker-test",
            auto_offset_reset="earliest",
        )
        bus = KafkaEventBus(config)
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        try:
            await bus.start()
            bus.subscribe("order.created", handler)
            await bus.publish(Event("order.created", {"order_id": "ORD-KAFKA-1"}))

            assert await _wait_for(lambda: len(received) >= 1, timeout=30.0), (
                "Kafka handler not called within timeout"
            )
        finally:
            await bus.stop()

        assert received[0].event_type == "order.created"
        assert received[0].data["order_id"] == "ORD-KAFKA-1"

    @pytest.mark.asyncio
    async def test_wildcard_handler(self, kafka_container) -> None:
        """A ``*`` wildcard handler must receive all published events."""
        from sagaz.choreography.buses.kafka import (
            KafkaEventBus,
            KafkaEventBusConfig,
        )

        bootstrap = kafka_container.get_bootstrap_server()
        config = KafkaEventBusConfig(
            bootstrap_servers=bootstrap,
            topic="test.choreography.wildcard",
            consumer_group="test-cg-wildcard",
            consumer_name="worker-test",
            auto_offset_reset="earliest",
        )
        bus = KafkaEventBus(config)
        received: list[str] = []

        try:
            await bus.start()
            bus.subscribe("*", lambda e: received.append(e.event_type))
            await bus.publish(Event("alpha.event"))
            await bus.publish(Event("beta.event"))

            assert await _wait_for(lambda: len(received) >= 2, timeout=30.0)
        finally:
            await bus.stop()

        assert "alpha.event" in received
        assert "beta.event" in received

    @pytest.mark.asyncio
    async def test_start_idempotent(self, kafka_container) -> None:
        """Calling start() twice must not create a duplicate reader task."""
        from sagaz.choreography.buses.kafka import (
            KafkaEventBus,
            KafkaEventBusConfig,
        )

        bootstrap = kafka_container.get_bootstrap_server()
        config = KafkaEventBusConfig(
            bootstrap_servers=bootstrap,
            topic="test.choreography.idem",
            consumer_group="test-cg-idem",
            consumer_name="worker-test",
            auto_offset_reset="latest",
        )
        bus = KafkaEventBus(config)
        try:
            await bus.start()
            first_task = bus._reader_task
            await bus.start()
            assert bus._reader_task is first_task
        finally:
            await bus.stop()


# ---------------------------------------------------------------------------
# RabbitMQ EventBus
# ---------------------------------------------------------------------------


@pytest.mark.xdist_group(name="containers")
class TestRabbitMQEventBusIntegration:
    """Integration tests for RabbitMQEventBus against a live RabbitMQ container."""

    def _amqp_url(self, container) -> str:
        try:
            return container.get_connection_url()
        except AttributeError:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(5672)
            return f"amqp://guest:guest@{host}:{port}/"

    @pytest.mark.asyncio
    async def test_publish_subscribe_round_trip(self, rabbitmq_container) -> None:
        """A published event must be received by a subscribed handler."""
        from sagaz.choreography.buses.rabbitmq import (
            RabbitMQEventBus,
            RabbitMQEventBusConfig,
        )

        config = RabbitMQEventBusConfig(
            url=self._amqp_url(rabbitmq_container),
            exchange_name="test.choreo",
            queue_name="test.choreo.queue",
        )
        bus = RabbitMQEventBus(config)
        received: list[Event] = []

        async def handler(e: Event) -> None:
            received.append(e)

        try:
            await bus.start()
            bus.subscribe("order.created", handler)
            await bus.publish(Event("order.created", {"order_id": "ORD-AMQ-1"}))

            assert await _wait_for(lambda: len(received) >= 1), (
                "RabbitMQ handler not called within timeout"
            )
        finally:
            await bus.stop()

        assert received[0].event_type == "order.created"
        assert received[0].data["order_id"] == "ORD-AMQ-1"

    @pytest.mark.asyncio
    async def test_wildcard_handler(self, rabbitmq_container) -> None:
        """A ``*`` wildcard handler must receive all published events."""
        from sagaz.choreography.buses.rabbitmq import (
            RabbitMQEventBus,
            RabbitMQEventBusConfig,
        )

        config = RabbitMQEventBusConfig(
            url=self._amqp_url(rabbitmq_container),
            exchange_name="test.choreo.wildcard",
            queue_name="test.choreo.wildcard.queue",
        )
        bus = RabbitMQEventBus(config)
        received: list[str] = []

        try:
            await bus.start()
            bus.subscribe("*", lambda e: received.append(e.event_type))
            await bus.publish(Event("alpha.event"))
            await bus.publish(Event("beta.event"))

            assert await _wait_for(lambda: len(received) >= 2)
        finally:
            await bus.stop()

        assert "alpha.event" in received
        assert "beta.event" in received

    @pytest.mark.asyncio
    async def test_start_idempotent(self, rabbitmq_container) -> None:
        """Calling start() twice must not reconnect."""
        from sagaz.choreography.buses.rabbitmq import (
            RabbitMQEventBus,
            RabbitMQEventBusConfig,
        )

        config = RabbitMQEventBusConfig(
            url=self._amqp_url(rabbitmq_container),
            exchange_name="test.choreo.idem",
            queue_name="test.choreo.idem.queue",
        )
        bus = RabbitMQEventBus(config)
        try:
            await bus.start()
            first_conn = bus._connection
            await bus.start()
            assert bus._connection is first_conn
        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self, rabbitmq_container) -> None:
        """Unsubscribed handler must not receive events published after unsubscription."""
        from sagaz.choreography.buses.rabbitmq import (
            RabbitMQEventBus,
            RabbitMQEventBusConfig,
        )

        config = RabbitMQEventBusConfig(
            url=self._amqp_url(rabbitmq_container),
            exchange_name="test.choreo.unsub",
            queue_name="test.choreo.unsub.queue",
        )
        bus = RabbitMQEventBus(config)
        calls = 0

        async def handler(e: Event) -> None:
            nonlocal calls
            calls += 1

        try:
            await bus.start()
            bus.subscribe("x.event", handler)
            await bus.publish(Event("x.event"))
            assert await _wait_for(lambda: calls >= 1)

            bus.unsubscribe("x.event", handler)
            before = calls
            await bus.publish(Event("x.event"))
            await asyncio.sleep(0.5)
        finally:
            await bus.stop()

        assert calls == before, "Handler received event after unsubscription"
