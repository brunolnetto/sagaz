"""A three-service order saga choreographed over a real broker (ADR-029, #56).

Orders, Inventory, Payments and Shipping each get their own bus instance and
consumer group, as separate processes would, plus a tracker. The happy path
must complete in order, and a declined payment must make Inventory release
its reservation, with the tracker reporting the transaction compensated.

Runs against Kafka and Redis Streams containers (skipped without Docker).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import uuid4

import pytest

from sagaz.choreography import ChoreographyEngine, ChoreographyTracker
from tests.unit.test_choreography_compensation import Inventory, Orders, Payments, Shipping

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

COMPLETION = {"order.shipped"}


def _redis_bus(container, topic: str, group: str):
    from sagaz.choreography.buses.redis_streams import RedisStreamsBusConfig, RedisStreamsEventBus

    host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
    config = RedisStreamsBusConfig(
        url=f"redis://{host}:{port}",
        stream_name=topic,
        consumer_group=group,
        consumer_name=f"{group}-1",
        block_timeout_ms=200,
    )
    return RedisStreamsEventBus(config)


def _kafka_bus(container, topic: str, group: str):
    from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig

    config = KafkaEventBusConfig(
        bootstrap_servers=container.get_bootstrap_server(),
        topic=topic,
        consumer_group=group,
        consumer_name=f"{group}-1",
        auto_offset_reset="earliest",
    )
    return KafkaEventBus(config)


BACKENDS: dict[str, tuple[str, Callable]] = {
    "redis": ("redis_container", _redis_bus),
    "kafka": ("kafka_container", _kafka_bus),
}


class Deployment:
    """One engine per service, each on its own bus instance and consumer group."""

    def __init__(self, make_bus: Callable[[str], object]) -> None:
        self.orders, self.inventory = Orders(name="orders"), Inventory()
        self.payments, self.shipping = Payments(), Shipping()
        self.engines = []
        for participant in (self.orders, self.inventory, self.payments, self.shipping):
            engine = ChoreographyEngine(make_bus(participant.name), completion_events=COMPLETION)
            engine.register(participant)
            self.engines.append(engine)
        self.tracker_bus = make_bus("tracker")
        self.tracker = ChoreographyTracker(self.tracker_bus, completion_events=COMPLETION)

    async def __aenter__(self) -> Deployment:
        for engine in self.engines:
            await engine._bus.start()
            await engine.start()
        await self.tracker_bus.start()
        await self.tracker.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.tracker.stop()
        await self.tracker_bus.stop()
        for engine in self.engines:
            await engine.stop()
            await engine._bus.stop()

    async def settled(self, correlation_id: str, timeout: float = 45.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            status = await self.tracker.status(correlation_id)
            if status and status.status in ("completed", "compensated", "failed"):
                return status
            await asyncio.sleep(0.2)
        return await self.tracker.status(correlation_id)


@pytest.fixture(params=sorted(BACKENDS))
def make_bus(request):
    fixture, factory = BACKENDS[request.param]
    container = request.getfixturevalue(fixture)
    topic = f"orders.{request.param}.{uuid4().hex[:8]}"
    return lambda group: factory(container, topic, group)


async def test_order_completes_across_three_services(make_bus):
    async with Deployment(make_bus) as deployment:
        start = await deployment.orders.begin(
            "order.created", {"order_id": "o-1", "amount": 40}, tenant_id="acme"
        )
        status = await deployment.settled(start.saga_id)

    assert status is not None
    assert status.status == "completed"
    assert status.tenant_id == "acme"
    assert deployment.inventory.reserved == ["o-1"]
    assert deployment.inventory.tenants == ["acme"]
    assert deployment.payments.charged == ["o-1"]
    assert {"order.created", "inventory.reserved", "payment.charged", "order.shipped"} <= {
        e["event_type"] for e in status.events
    }


async def test_declined_payment_is_compensated_across_services(make_bus):
    async with Deployment(make_bus) as deployment:
        start = await deployment.orders.begin("order.created", {"order_id": "o-2", "amount": 500})
        status = await deployment.settled(start.saga_id)

    assert status is not None
    assert status.status == "compensated"
    assert status.failure["participant"] == "payments"
    assert deployment.inventory.released == ["o-2"]
    assert deployment.payments.charged == []
