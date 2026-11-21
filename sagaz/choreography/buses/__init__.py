"""
sagaz.choreography.buses — broker-agnostic EventBus transport backends.

Four implementations are provided, all sharing the ``AbstractEventBus`` API:

``EventBus``
    In-process asyncio pub/sub.  Zero dependencies; ideal for single-process
    sagas, unit tests, and local development.  Imported from
    ``sagaz.choreography.events``.

``RedisStreamsEventBus``
    Distributed pub/sub backed by Redis Streams (XADD / XREADGROUP).  Requires
    the ``redis`` optional extra (``sagaz[redis]``).

``KafkaEventBus``
    Distributed pub/sub backed by Apache Kafka.  Requires the ``aiokafka``
    optional extra (``sagaz[kafka]``).

``RabbitMQEventBus``
    Distributed pub/sub backed by RabbitMQ / AMQP (topic exchange).  Requires
    the ``aio-pika`` optional extra (``sagaz[rabbitmq]``).

Use ``create_event_bus(backend)`` to select a backend at runtime::

    from sagaz.choreography.buses import create_event_bus, BusBackend

    bus = create_event_bus(BusBackend.REDIS)
    await bus.start()
    bus.subscribe("order.created", my_handler)
    await bus.publish(Event("order.created", {"order_id": "ORD-1"}))
    await bus.stop()
"""

from typing import TYPE_CHECKING

from sagaz.choreography.buses.factory import BusBackend, create_event_bus
from sagaz.choreography.events import AbstractEventBus

if TYPE_CHECKING:
    from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig
    from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus, RabbitMQEventBusConfig
    from sagaz.choreography.buses.redis_streams import (
        RedisStreamsBusConfig,
        RedisStreamsEventBus,
    )

__all__ = [
    "AbstractEventBus",
    "BusBackend",
    "KafkaEventBus",
    "KafkaEventBusConfig",
    "RabbitMQEventBus",
    "RabbitMQEventBusConfig",
    "RedisStreamsBusConfig",
    "RedisStreamsEventBus",
    "create_event_bus",
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
