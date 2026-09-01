"""
Unit tests for create_event_bus factory.
"""

from __future__ import annotations

import pytest

from sagaz.choreography.buses.factory import BusBackend, create_event_bus
from sagaz.choreography.events import AbstractEventBus, EventBus


def test_memory_returns_event_bus() -> None:
    bus = create_event_bus("memory")
    assert isinstance(bus, EventBus)
    assert isinstance(bus, AbstractEventBus)


def test_memory_via_enum() -> None:
    bus = create_event_bus(BusBackend.MEMORY)
    assert isinstance(bus, EventBus)


def test_redis_returns_redis_streams_bus() -> None:
    from sagaz.choreography.buses.redis_streams import RedisStreamsEventBus

    bus = create_event_bus("redis")
    assert isinstance(bus, RedisStreamsEventBus)
    assert isinstance(bus, AbstractEventBus)


def test_kafka_returns_kafka_bus() -> None:
    from sagaz.choreography.buses.kafka import KafkaEventBus

    bus = create_event_bus("kafka")
    assert isinstance(bus, KafkaEventBus)
    assert isinstance(bus, AbstractEventBus)


def test_rabbitmq_returns_rabbitmq_bus() -> None:
    from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus

    bus = create_event_bus("rabbitmq")
    assert isinstance(bus, RabbitMQEventBus)
    assert isinstance(bus, AbstractEventBus)


def test_unknown_backend_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown bus backend"):
        create_event_bus("nats")


def test_backend_enum_values() -> None:
    assert BusBackend.MEMORY == "memory"
    assert BusBackend.REDIS == "redis"
    assert BusBackend.KAFKA == "kafka"
    assert BusBackend.RABBITMQ == "rabbitmq"
