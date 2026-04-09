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

from sagaz.choreography.buses.factory import BusBackend, create_event_bus
from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig
from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus, RabbitMQEventBusConfig
from sagaz.choreography.buses.redis_streams import (
    RedisStreamsBusConfig,
    RedisStreamsEventBus,
)
from sagaz.choreography.events import AbstractEventBus

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
