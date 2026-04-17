"""
EventBus factory — create a broker-specific transport from a string key.

Usage::

    from sagaz.choreography.buses import create_event_bus, BusBackend

    # In-process (default, zero dependencies)
    bus = create_event_bus("memory")

    # Redis Streams (requires sagaz[redis])
    bus = create_event_bus("redis", RedisStreamsBusConfig(url="redis://localhost:6379/0"))

    # Apache Kafka (requires sagaz[kafka])
    bus = create_event_bus("kafka", KafkaEventBusConfig(bootstrap_servers="localhost:9092"))

    # RabbitMQ / AMQP (requires sagaz[rabbitmq])
    bus = create_event_bus("rabbitmq", RabbitMQEventBusConfig(url="amqp://guest:guest@localhost/"))

Or use the ``BusBackend`` enum for type-safe selection::

    bus = create_event_bus(BusBackend.KAFKA)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sagaz.choreography.events import AbstractEventBus


class BusBackend(StrEnum):
    """Enumeration of supported EventBus transport backends."""

    MEMORY = "memory"
    REDIS = "redis"
    KAFKA = "kafka"
    RABBITMQ = "rabbitmq"


def create_event_bus(
    backend: str | BusBackend,
    config: Any = None,
) -> AbstractEventBus:
    """
    Instantiate an ``AbstractEventBus`` for the given *backend*.

    Parameters
    ----------
    backend:
        One of ``"memory"``, ``"redis"``, ``"kafka"``, or ``"rabbitmq"``
        (case-insensitive).  Can also be a ``BusBackend`` enum value.
    config:
        Optional backend-specific configuration dataclass.  When *None*,
        the backend reads from environment variables via ``from_env()``.

    Returns
    -------
    AbstractEventBus
        A concrete bus instance.  Call ``await bus.start()`` before use.

    Raises
    ------
    ValueError
        If *backend* is not a recognised value.
    MissingDependencyError
        If the required optional package is not installed.
    """
    try:
        backend = BusBackend(str(backend).lower())
    except ValueError:
        valid = [b.value for b in BusBackend]
        msg = f"Unknown bus backend {backend!r}. Valid values: {valid}"
        raise ValueError(msg) from None

    if backend is BusBackend.MEMORY:
        from sagaz.choreography.events import EventBus

        return EventBus()

    if backend is BusBackend.REDIS:
        from sagaz.choreography.buses.redis_streams import RedisStreamsEventBus

        return RedisStreamsEventBus(config)

    if backend is BusBackend.KAFKA:
        from sagaz.choreography.buses.kafka import KafkaEventBus

        return KafkaEventBus(config)

    # backend is BusBackend.RABBITMQ
    from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus

    return RabbitMQEventBus(config)
