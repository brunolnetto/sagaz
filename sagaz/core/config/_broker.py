"""Message broker configuration management.

Handles initialization, validation, and construction of message broker backends
from various sources (environment, files, URLs).
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagaz.outbox.brokers.base import BaseBroker

logger = logging.getLogger(__name__)


class BrokerConfigManager:
    """Manages message broker backend configuration and initialization."""

    @classmethod
    def from_env(cls, env: object) -> "BaseBroker | None":
        """Construct a broker descriptor from environment variables.

        Checks SAGAZ_BROKER_URL first; falls back to
        SAGAZ_BROKER_TYPE + individual connection vars.
        Returns None when no broker is configured.

        Args:
            env: Environment configuration object

        Returns:
            Broker backend instance or None
        """
        broker_url = env.get("SAGAZ_BROKER_URL", "")  # type: ignore
        if broker_url:
            return cls._parse_broker_url(broker_url)

        broker_type = env.get("SAGAZ_BROKER_TYPE", "")  # type: ignore
        if broker_type == "kafka":
            host = env.get("SAGAZ_BROKER_HOST", "localhost")  # type: ignore
            port = env.get("SAGAZ_BROKER_PORT", "9092")  # type: ignore
            return cls._parse_broker_url(f"kafka://{host}:{port}")
        if broker_type == "rabbitmq":
            host = env.get("SAGAZ_BROKER_HOST", "localhost")  # type: ignore
            port = env.get("SAGAZ_BROKER_PORT", "5672")  # type: ignore
            user = env.get("SAGAZ_BROKER_USER", "guest")  # type: ignore
            password = env.get("SAGAZ_BROKER_PASSWORD", "guest")  # type: ignore
            return cls._parse_broker_url(
                f"amqp://{user}:{password}@{host}:{port}/"
            )
        if broker_type == "redis":
            redis_url = env.get("SAGAZ_BROKER_URL")  # type: ignore
            if redis_url is None:
                redis_url = "redis://localhost:6379/1"
            return cls._parse_broker_url(redis_url)
        return None

    @classmethod
    def from_config_dict(cls, broker_data: dict) -> "BaseBroker | None":
        """Build broker instance from configuration dictionary.

        Args:
            broker_data: Dictionary with 'type' and 'connection' keys

        Returns:
            Broker instance or None if no broker configured
        """
        if not broker_data:
            return None

        b_type = broker_data.get("type", "").lower()
        conn = broker_data.get("connection", {})

        if b_type == "kafka":
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

            host = conn.get("host", "localhost")
            port = conn.get("port", 9092)
            kafka_config = KafkaBrokerConfig(bootstrap_servers=f"{host}:{port}")
            return KafkaBroker(kafka_config)

        if b_type == "redis":
            from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

            host = conn.get("host", "localhost")
            port = conn.get("port", 6379)
            redis_config = RedisBrokerConfig(url=f"redis://{host}:{port}")
            return RedisBroker(redis_config)

        if b_type in ("rabbitmq", "amqp"):
            from sagaz.outbox.brokers.rabbitmq import (
                RabbitMQBroker,
                RabbitMQBrokerConfig,
            )

            user = conn.get("user", "guest")
            port = conn.get("port", 5672)
            pwd = conn.get("password", "guest")
            host = conn.get("host", "localhost")
            url = f"amqp://{user}:{pwd}@{host}:{port}/"
            rmq_config = RabbitMQBrokerConfig(url=url)
            return RabbitMQBroker(rmq_config)

        return None

    @staticmethod
    def _parse_broker_url(url: str) -> "BaseBroker":
        """Parse broker URL and return appropriate broker instance.

        Args:
            url: Broker connection URL (kafka://, redis://, amqp://, etc.)

        Returns:
            Broker backend instance

        Raises:
            ValueError: If URL scheme is unknown
        """
        if url.startswith("kafka://"):
            from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

            # Extract bootstrap servers from URL
            servers = url.replace("kafka://", "")
            kafka_config = KafkaBrokerConfig(bootstrap_servers=servers)
            return KafkaBroker(kafka_config)
        if url.startswith("redis://"):
            from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig

            redis_config = RedisBrokerConfig(url=url)
            return RedisBroker(redis_config)
        if url.startswith(("amqp://", "rabbitmq://")):
            from sagaz.outbox.brokers.rabbitmq import (
                RabbitMQBroker,
                RabbitMQBrokerConfig,
            )

            rmq_config = RabbitMQBrokerConfig(
                url=url.replace("rabbitmq://", "amqp://")
            )
            return RabbitMQBroker(rmq_config)
        if url == "memory://" or url == "":
            from sagaz.outbox.brokers.memory import InMemoryBroker

            return InMemoryBroker()
        msg = f"Unknown broker URL scheme: {url}"
        raise ValueError(msg)
