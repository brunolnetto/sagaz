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


def get_cdc_source():
    """The CDC source selected by the environment, or ``None`` for polling mode.

    ``SAGAZ_OUTBOX_MODE=cdc`` enables CDC (ADR-011); ``SAGAZ_CDC_SOURCE`` picks
    ``pg_logical`` (default: PostgreSQL logical replication of ``SAGAZ_CDC_DSN`` or
    ``DATABASE_URL``, slot ``SAGAZ_CDC_SLOT``, publication
    ``SAGAZ_CDC_PUBLICATION``) or ``debezium`` (Kafka at
    ``KAFKA_BOOTSTRAP_SERVERS``, topic prefix ``SAGAZ_CDC_TOPIC_PREFIX``,
    consumer group ``SAGAZ_CDC_GROUP_ID``).
    """
    mode = os.getenv("SAGAZ_OUTBOX_MODE", "polling").lower()
    if mode == "polling":
        return None
    if mode != "cdc":
        logger.error(f"SAGAZ_OUTBOX_MODE must be 'polling' or 'cdc', not {mode!r}")
        sys.exit(1)

    kind = os.getenv("SAGAZ_CDC_SOURCE", "pg_logical").lower()
    if kind == "pg_logical":
        from sagaz.integrations.cdc.pg_logical import PgLogicalSource

        dsn = os.getenv("SAGAZ_CDC_DSN") or os.getenv("DATABASE_URL")
        if not dsn:
            logger.error("SAGAZ_CDC_DSN or DATABASE_URL is required for pg_logical CDC")
            sys.exit(1)
        return PgLogicalSource(
            dsn,
            slot=os.getenv("SAGAZ_CDC_SLOT", "sagaz_outbox"),
            publication=os.getenv("SAGAZ_CDC_PUBLICATION", "sagaz_outbox_pub"),
        )
    if kind == "debezium":
        from sagaz.integrations.cdc.debezium import DebeziumKafkaSource

        return DebeziumKafkaSource(
            os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            topic_prefix=os.getenv("SAGAZ_CDC_TOPIC_PREFIX", "sagaz"),
            group_id=os.getenv("SAGAZ_CDC_GROUP_ID", "sagaz-cdc"),
        )
    logger.error(f"SAGAZ_CDC_SOURCE must be 'pg_logical' or 'debezium', not {kind!r}")
    sys.exit(1)


def cdc_config_from_env() -> dict:
    """``OutboxConfig`` overrides for the CDC sweep (seconds; ``0`` disables the sweep)."""
    interval = float(os.getenv("SAGAZ_CDC_SWEEP_INTERVAL", "30"))
    return {
        "cdc_sweep_interval_seconds": interval or None,
        "cdc_sweep_min_age_seconds": float(os.getenv("SAGAZ_CDC_SWEEP_MIN_AGE", "30")),
    }
