"""
sagaz.choreography — Saga Choreography Pattern.

Choreography is an alternative to orchestration where services react to events
independently. Unlike ``Saga`` (which has a central coordinator), a
``ChoreographedSaga`` declares event handlers using the ``@on_event`` decorator
and publishes new events via an ``AbstractEventBus`` implementation.

Public API::

    from sagaz.choreography import (
        AbstractEventBus,
        BusBackend,
        ChoreographedSaga,
        Event,
        EventBus,
        ChoreographyEngine,
        KafkaEventBus,
        KafkaEventBusConfig,
        RabbitMQEventBus,
        RabbitMQEventBusConfig,
        RedisStreamsBusConfig,
        RedisStreamsEventBus,
        create_event_bus,
        on_event,
    )

Quick start (in-process bus)::

    bus = EventBus()
    engine = ChoreographyEngine(bus)

    class OrderSaga(ChoreographedSaga):
        @on_event("order.created")
        async def handle_order_created(self, event: Event) -> None:
            await bus.publish(Event("inventory.reserve", {"order_id": event.data["order_id"]}))

    saga = OrderSaga()
    engine.register(saga)
    await engine.start()
    await bus.publish(Event("order.created", {"order_id": "ORD-1"}))
    await engine.stop()

Selecting a broker at runtime::

    from sagaz.choreography import create_event_bus, BusBackend

    bus = create_event_bus(BusBackend.REDIS)          # Redis Streams
    bus = create_event_bus(BusBackend.KAFKA)          # Apache Kafka
    bus = create_event_bus(BusBackend.RABBITMQ)       # RabbitMQ / AMQP
    bus = create_event_bus(BusBackend.MEMORY)         # in-process (default)
"""

from typing import TYPE_CHECKING

from sagaz.choreography.buses import BusBackend, create_event_bus
from sagaz.choreography.decorators import compensate, on_event
from sagaz.choreography.engine import ChoreographyEngine
from sagaz.choreography.events import COMPENSATE, COMPENSATED, AbstractEventBus, Event, EventBus
from sagaz.choreography.saga import ChoreographedSaga
from sagaz.choreography.tracker import ChoreographyTracker, TransactionStatus, load_status

if TYPE_CHECKING:
    from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig
    from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus, RabbitMQEventBusConfig
    from sagaz.choreography.buses.redis_streams import (
        RedisStreamsBusConfig,
        RedisStreamsEventBus,
    )

__all__ = [
    "COMPENSATE",
    "COMPENSATED",
    "AbstractEventBus",
    "BusBackend",
    "ChoreographedSaga",
    "ChoreographyEngine",
    "ChoreographyTracker",
    "Event",
    "EventBus",
    "KafkaEventBus",
    "KafkaEventBusConfig",
    "RabbitMQEventBus",
    "RabbitMQEventBusConfig",
    "RedisStreamsBusConfig",
    "RedisStreamsEventBus",
    "TransactionStatus",
    "compensate",
    "create_event_bus",
    "load_status",
    "on_event",
]

# Each bus imports its broker client (aiokafka, aio_pika, redis), which is slow to
# import: load a bus on first use, not with ``import sagaz``.
_LAZY_BUSES = {
    "KafkaEventBus": "sagaz.choreography.buses.kafka",
    "KafkaEventBusConfig": "sagaz.choreography.buses.kafka",
    "RabbitMQEventBus": "sagaz.choreography.buses.rabbitmq",
    "RabbitMQEventBusConfig": "sagaz.choreography.buses.rabbitmq",
    "RedisStreamsBusConfig": "sagaz.choreography.buses.redis_streams",
    "RedisStreamsEventBus": "sagaz.choreography.buses.redis_streams",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_BUSES:
        import importlib

        return getattr(importlib.import_module(_LAZY_BUSES[name]), name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
