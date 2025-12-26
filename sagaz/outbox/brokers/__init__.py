"""
Outbox Broker Implementations

Provides message broker backends for the transactional outbox pattern.

Available backends:
    - InMemoryBroker: For testing
    - KafkaBroker: Apache Kafka (requires aiokafka)
    - RabbitMQBroker: RabbitMQ/AMQP (requires aio-pika)
    - RedisBroker: Redis Streams (requires redis)

Factory:
    >>> from sagaz.outbox.brokers import create_broker
    >>> broker = create_broker("kafka", bootstrap_servers="localhost:9092")
"""

from sagaz.outbox.brokers.base import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerError,
    BrokerPublishError,
    MessageBroker,
)
from sagaz.outbox.brokers.factory import (
    create_broker,
    create_broker_from_env,
    get_available_brokers,
    print_available_brokers,
)
from sagaz.outbox.brokers.memory import InMemoryBroker


# Lazy imports for optional backends
def KafkaBroker(*args, **kwargs):
    """Kafka message broker (requires aiokafka)."""
    from sagaz.outbox.brokers.kafka import KafkaBroker as _Impl
    return _Impl(*args, **kwargs)


def RabbitMQBroker(*args, **kwargs):
    """RabbitMQ message broker (requires aio-pika)."""
    from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker as _Impl
    return _Impl(*args, **kwargs)


def RedisBroker(*args, **kwargs):
    """Redis Streams message broker (requires redis)."""
    from sagaz.outbox.brokers.redis import RedisBroker as _Impl
    return _Impl(*args, **kwargs)


__all__ = [
    # Base
    "MessageBroker",
    "BaseBroker",
    "BrokerConfig",
    "BrokerError",
    "BrokerConnectionError",
    "BrokerPublishError",

    # Implementations
    "InMemoryBroker",
    "KafkaBroker",
    "RabbitMQBroker",
    "RedisBroker",

    # Factory
    "create_broker",
    "create_broker_from_env",
    "get_available_brokers",
    "print_available_brokers",
]
