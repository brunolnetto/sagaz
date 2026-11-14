"""
Environment-driven construction of the outbox worker's storage and broker.

Used by the ``python -m sagaz.core.outbox.worker`` entry point; the public
factories are re-exported from :mod:`sagaz.core.outbox.worker`.
"""

import os
import sys

from sagaz.core.outbox._worker_logging import logger


def get_storage():
    """Create storage backend from environment."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    return PostgreSQLOutboxStorage(connection_string=database_url)


def _get_broker_url(broker_type: str) -> str:
    """Get broker URL from environment based on broker type."""
    if broker_type == "rabbitmq":
        return os.getenv("RABBITMQ_URL", "") or os.getenv("BROKER_URL", "")
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "") or os.getenv("BROKER_URL", "")


def _create_kafka_broker(broker_url: str):
    """Create Kafka broker instance."""
    from sagaz.core.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

    config = KafkaBrokerConfig(bootstrap_servers=broker_url)
    return KafkaBroker(config=config)


def _create_rabbitmq_broker(broker_url: str):
    """Create RabbitMQ broker instance."""
    from sagaz.core.outbox.brokers.rabbitmq import RabbitMQBroker, RabbitMQBrokerConfig

    config = RabbitMQBrokerConfig(
        url=broker_url,
        exchange_name=os.getenv("RABBITMQ_EXCHANGE", "saga-events"),
    )
    return RabbitMQBroker(config=config)


_BROKER_FACTORIES = {
    "kafka": _create_kafka_broker,
    "rabbitmq": _create_rabbitmq_broker,
}


def get_broker():
    """Create broker from environment."""
    broker_type = os.getenv("BROKER_TYPE", "kafka").lower()
    broker_url = _get_broker_url(broker_type)

    if not broker_url:
        logger.error(f"No broker URL configured. Set BROKER_URL or {broker_type.upper()}_URL")
        sys.exit(1)

    factory = _BROKER_FACTORIES.get(broker_type)
    if not factory:
        logger.error(f"Unknown broker type: {broker_type}")
        sys.exit(1)

    return factory(broker_url)
