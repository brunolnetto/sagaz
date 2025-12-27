"""
Broker Factory - Easy creation of message broker instances.

Provides a unified API for creating brokers without importing specific classes.

Usage:
    >>> from sagaz.outbox.brokers import create_broker, get_available_brokers
    >>>
    >>> # Check available brokers
    >>> print(get_available_brokers())
    ['memory', 'kafka', 'rabbitmq']
    >>>
    >>> # Create a broker
    >>> broker = create_broker("kafka", bootstrap_servers="localhost:9092")
    >>> await broker.connect()
"""

from typing import Any

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox.brokers.base import MessageBroker
from sagaz.outbox.brokers.memory import InMemoryBroker


def _check_broker_availability(module_path: str, available_attr: str) -> bool:
    """Check if a broker module is available."""
    try:
        module = __import__(module_path, fromlist=[available_attr])
        return getattr(module, available_attr, False)
    except ImportError:
        return False


def get_available_brokers() -> list[str]:
    """
    Get list of available broker backends.

    Returns:
        List of broker names that can be used
    """
    available = ["memory"]  # Always available

    broker_checks = [
        ("sagaz.outbox.brokers.kafka", "KAFKA_AVAILABLE", "kafka"),
        ("sagaz.outbox.brokers.rabbitmq", "RABBITMQ_AVAILABLE", "rabbitmq"),
        ("sagaz.outbox.brokers.redis", "REDIS_AVAILABLE", "redis"),
    ]

    for module_path, attr, name in broker_checks:
        if _check_broker_availability(module_path, attr):
            available.append(name)

    return available


def print_available_brokers() -> None:
    """Print available brokers with installation instructions."""
    print("\n=== Available Message Brokers ===\n")

    # Memory (always available)
    print("  ✓ memory     - In-memory (for testing)")

    # Broker definitions: (module_path, available_attr, name, description, install_cmd)
    brokers = [
        (
            "sagaz.outbox.brokers.kafka",
            "KAFKA_AVAILABLE",
            "kafka",
            "Apache Kafka",
            "pip install aiokafka",
        ),
        (
            "sagaz.outbox.brokers.rabbitmq",
            "RABBITMQ_AVAILABLE",
            "rabbitmq",
            "RabbitMQ/AMQP",
            "pip install aio-pika",
        ),
        (
            "sagaz.outbox.brokers.redis",
            "REDIS_AVAILABLE",
            "redis",
            "Redis Streams",
            "pip install redis",
        ),
    ]

    for module_path, attr, name, desc, install in brokers:
        _print_broker_status(module_path, attr, name, desc, install)

    print()


def _print_broker_status(module_path: str, attr: str, name: str, desc: str, install: str) -> None:
    """Print status line for a broker."""
    available = _check_broker_availability(module_path, attr)
    if available:
        print(f"  ✓ {name:<10} - {desc}")
    else:
        print(f"  ✗ {name:<10} - {desc} (install: {install})")


def _create_kafka_broker(kwargs: dict):
    """Create Kafka broker instance."""
    from sagaz.outbox.brokers.kafka import KAFKA_AVAILABLE, KafkaBroker, KafkaBrokerConfig

    if not KAFKA_AVAILABLE:
        msg = "aiokafka"
        raise MissingDependencyError(msg, "Kafka message broker")
    config = KafkaBrokerConfig(**kwargs) if kwargs else None
    return KafkaBroker(config)


def _create_rabbitmq_broker(kwargs: dict):
    """Create RabbitMQ broker instance."""
    from sagaz.outbox.brokers.rabbitmq import (
        RABBITMQ_AVAILABLE,
        RabbitMQBroker,
        RabbitMQBrokerConfig,
    )

    if not RABBITMQ_AVAILABLE:
        msg = "aio-pika"
        raise MissingDependencyError(msg, "RabbitMQ message broker")
    config = RabbitMQBrokerConfig(**kwargs) if kwargs else None
    return RabbitMQBroker(config)


def _create_redis_broker(kwargs: dict):
    """Create Redis broker instance."""
    from sagaz.outbox.brokers.redis import REDIS_AVAILABLE, RedisBroker, RedisBrokerConfig

    if not REDIS_AVAILABLE:
        msg = "redis"
        raise MissingDependencyError(msg, "Redis message broker")
    config = RedisBrokerConfig(**kwargs) if kwargs else None
    return RedisBroker(config)


# Broker registry: type -> (factory_function, dependency_name)
_BROKER_REGISTRY = {
    "memory": (lambda _: InMemoryBroker(), None),
    "kafka": (_create_kafka_broker, "aiokafka"),
    "rabbitmq": (_create_rabbitmq_broker, "aio-pika"),
    "rabbit": (_create_rabbitmq_broker, "aio-pika"),
    "amqp": (_create_rabbitmq_broker, "aio-pika"),
    "redis": (_create_redis_broker, "redis"),
}


def create_broker(
    broker_type: str,
    **kwargs: Any,
) -> MessageBroker:
    """
    Create a message broker instance.

    Args:
        broker_type: Type of broker ('memory', 'kafka', 'rabbitmq', 'redis')
        **kwargs: Broker-specific configuration

    Returns:
        Configured broker instance

    Raises:
        MissingDependencyError: If required package is not installed
        ValueError: If broker type is unknown

    Examples:
        >>> # In-memory broker for testing
        >>> broker = create_broker("memory")
        >>>
        >>> # Kafka broker
        >>> broker = create_broker("kafka", bootstrap_servers="localhost:9092")
        >>>
        >>> # RabbitMQ broker
        >>> broker = create_broker("rabbitmq", url="amqp://guest:guest@localhost/")
    """
    broker_type = broker_type.lower().strip()

    if broker_type not in _BROKER_REGISTRY:
        available = get_available_brokers()
        msg = f"Unknown broker type: '{broker_type}'\nAvailable brokers: {', '.join(available)}"
        raise ValueError(msg)

    factory, dependency = _BROKER_REGISTRY[broker_type]

    try:
        return factory(kwargs)  # type: ignore[no-any-return]
    except ImportError:
        if dependency:
            raise MissingDependencyError(dependency, f"{broker_type} message broker")
        raise  # pragma: no cover


def create_broker_from_env() -> MessageBroker:
    """
    Create a message broker from environment variables.

    Reads BROKER_TYPE environment variable to determine which
    broker to create, then uses broker-specific env vars.

    Environment Variables:
        BROKER_TYPE: Broker type (kafka, rabbitmq, memory)

        For Kafka:
            KAFKA_BOOTSTRAP_SERVERS
            KAFKA_CLIENT_ID
            KAFKA_SASL_USERNAME
            KAFKA_SASL_PASSWORD

        For RabbitMQ:
            RABBITMQ_URL
            RABBITMQ_EXCHANGE

    Returns:
        Configured broker instance
    """
    import os

    broker_type = os.getenv("BROKER_TYPE", "memory").lower()

    if broker_type == "memory":
        return InMemoryBroker()

    if broker_type == "kafka":
        from sagaz.outbox.brokers.kafka import KafkaBroker

        return KafkaBroker.from_env()

    if broker_type in ("rabbitmq", "rabbit", "amqp"):
        from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

        return RabbitMQBroker.from_env()

    if broker_type == "redis":
        from sagaz.outbox.brokers.redis import RedisBroker

        return RedisBroker.from_env()

    msg = f"Unknown BROKER_TYPE: {broker_type}"
    raise ValueError(msg)
