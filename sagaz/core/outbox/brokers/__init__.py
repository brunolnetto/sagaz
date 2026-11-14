"""
Outbox Broker Implementations

Provides message broker backends for the transactional outbox pattern.

Available backends:
    - InMemoryBroker: For testing
    - KafkaBroker: Apache Kafka (requires aiokafka)
    - RabbitMQBroker: RabbitMQ/AMQP (requires aio-pika)
    - RedisBroker: Redis Streams (requires redis)

Factory:
    >>> from sagaz.core.outbox.brokers import create_broker
    >>> broker = create_broker("kafka", bootstrap_servers="localhost:9092")
"""

from sagaz.core.outbox.brokers._lazy import KafkaBroker, RabbitMQBroker, RedisBroker
from sagaz.core.outbox.brokers.base import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerError,
    BrokerPublishError,
    MessageBroker,
)
from sagaz.core.outbox.brokers.factory import (
    create_broker,
    create_broker_from_env,
    get_available_brokers,
    print_available_brokers,
)
from sagaz.core.outbox.brokers.memory import InMemoryBroker

__all__ = [
    "BaseBroker",
    "BrokerConfig",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerPublishError",
    # Implementations
    "InMemoryBroker",
    "KafkaBroker",
    # Base
    "MessageBroker",
    "RabbitMQBroker",
    "RedisBroker",
    # Factory
    "create_broker",
    "create_broker_from_env",
    "get_available_brokers",
    "print_available_brokers",
]
