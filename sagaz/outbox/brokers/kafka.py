"""
Kafka Message Broker - Production-ready Kafka integration.

Uses aiokafka for async Kafka producer with idempotent delivery.

Usage:
    >>> from sagaz.outbox.brokers import KafkaBroker
    >>>
    >>> broker = KafkaBroker(bootstrap_servers="localhost:9092")
    >>> await broker.connect()
    >>> await broker.publish("orders", b'{"order_id": 1}')
"""

import logging
from dataclasses import dataclass

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox.brokers.base import (
    BaseBroker,
    BrokerConfig,
    BrokerConnectionError,
    BrokerPublishError,
)

# Check for aiokafka availability
try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaProducer = None  # pragma: no cover
    KafkaError = Exception  # pragma: no cover

logger = logging.getLogger(__name__)


@dataclass
class KafkaBrokerConfig(BrokerConfig):
    """
    Kafka-specific broker configuration.

    Attributes:
        bootstrap_servers: Kafka bootstrap servers (comma-separated)
        client_id: Client identifier
        acks: Acknowledgment mode ('all', 1, 0)
        enable_idempotence: Enable idempotent producer
        max_batch_size: Max batch size in bytes
        linger_ms: Linger time before sending batch
        compression_type: Compression (gzip, snappy, lz4, zstd, None)
        request_timeout_ms: Request timeout
        sasl_mechanism: SASL mechanism (PLAIN, SCRAM-SHA-256, etc.)
        sasl_username: SASL username
        sasl_password: SASL password
        security_protocol: Security protocol (PLAINTEXT, SASL_SSL, etc.)
    """

    bootstrap_servers: str = "localhost:9092"
    client_id: str = "sage-outbox"
    acks: str = "all"
    enable_idempotence: bool = True
    max_batch_size: int = 16384
    linger_ms: int = 5
    compression_type: str | None = "gzip"
    request_timeout_ms: int = 30000

    # Security
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    security_protocol: str = "PLAINTEXT"


class KafkaBroker(BaseBroker):
    """
    Kafka message broker using aiokafka.

    Features:
        - Idempotent producer for exactly-once semantics
        - Automatic batching for throughput
        - Compression support
        - SASL/SSL authentication
        - Graceful shutdown

    Usage:
        >>> config = KafkaBrokerConfig(
        ...     bootstrap_servers="localhost:9092",
        ...     enable_idempotence=True,
        ... )
        >>> broker = KafkaBroker(config)
        >>> await broker.connect()
        >>>
        >>> await broker.publish(
        ...     topic="orders",
        ...     message=b'{"order_id": "123"}',
        ...     key="order-123",
        ...     headers={"trace_id": "abc"},
        ... )
        >>>
        >>> await broker.close()
    """

    def __init__(self, config: KafkaBrokerConfig | None = None):
        """
        Initialize Kafka broker.

        Args:
            config: Kafka configuration

        Raises:
            MissingDependencyError: If aiokafka is not installed
        """
        if not KAFKA_AVAILABLE:
            msg = "aiokafka"
            raise MissingDependencyError(msg, "Kafka message broker")  # pragma: no cover

        super().__init__(config)
        self.config: KafkaBrokerConfig = config or KafkaBrokerConfig()
        self._producer: AIOKafkaProducer | None = None
        self._connected = False

    @classmethod
    def from_env(cls) -> "KafkaBroker":
        """Create Kafka broker from environment variables."""
        import os

        config = KafkaBrokerConfig(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            client_id=os.getenv("KAFKA_CLIENT_ID", "sage-outbox"),
            sasl_mechanism=os.getenv("KAFKA_SASL_MECHANISM"),
            sasl_username=os.getenv("KAFKA_SASL_USERNAME"),
            sasl_password=os.getenv("KAFKA_SASL_PASSWORD"),
            security_protocol=os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
        )
        return cls(config)

    async def connect(self) -> None:
        """Establish connection to Kafka."""
        if self._connected:
            return

        try:
            producer_kwargs = {
                "bootstrap_servers": self.config.bootstrap_servers,
                "client_id": self.config.client_id,
                "acks": self.config.acks,
                "enable_idempotence": self.config.enable_idempotence,
                "max_batch_size": self.config.max_batch_size,
                "linger_ms": self.config.linger_ms,
                "request_timeout_ms": self.config.request_timeout_ms,
            }

            if self.config.compression_type:
                producer_kwargs["compression_type"] = self.config.compression_type

            # Add security settings if configured
            if self.config.sasl_mechanism:  # pragma: no cover
                producer_kwargs["sasl_mechanism"] = self.config.sasl_mechanism
                producer_kwargs["sasl_plain_username"] = self.config.sasl_username
                producer_kwargs["sasl_plain_password"] = self.config.sasl_password
                producer_kwargs["security_protocol"] = self.config.security_protocol

            self._producer = AIOKafkaProducer(**producer_kwargs)
            await self._producer.start()
            self._connected = True

            logger.info(f"Connected to Kafka at {self.config.bootstrap_servers}")

        except KafkaError as e:  # pragma: no cover
            msg = f"Failed to connect to Kafka: {e}"
            raise BrokerConnectionError(msg) from e

    async def publish(  # pragma: no cover
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """Publish a message to Kafka."""
        if not self._connected or not self._producer:  # pragma: no cover
            msg = "Kafka producer not connected"
            raise BrokerConnectionError(msg)

        try:
            await self._producer.send_and_wait(
                topic=topic,
                value=message,
                key=self._encode_key(key),
                headers=self._convert_headers(headers),
            )
            logger.debug(f"Published message to Kafka topic {topic}")

        except KafkaError as e:  # pragma: no cover
            msg = f"Failed to publish to Kafka: {e}"
            raise BrokerPublishError(msg) from e

    @staticmethod
    def _convert_headers(headers: dict[str, str] | None) -> list | None:
        """Convert headers dict to Kafka format."""
        if not headers:
            return None
        return [(k, v.encode("utf-8") if isinstance(v, str) else v) for k, v in headers.items()]

    @staticmethod
    def _encode_key(key: str | None) -> bytes | None:
        """Encode key to bytes if provided."""
        return key.encode("utf-8") if key else None

    async def close(self) -> None:  # pragma: no cover
        """Close the Kafka producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
        self._connected = False
        logger.info("Kafka producer closed")

    async def health_check(self) -> bool:  # pragma: no cover
        """Check Kafka connection health."""
        if not self._connected or not self._producer:  # pragma: no cover
            return False

        try:
            # Try to get cluster metadata as a health check
            await self._producer.client.fetch_all_metadata()
            return True
        except Exception:  # pragma: no cover
            return False


def is_kafka_available() -> bool:
    """Check if Kafka support is available."""
    return KAFKA_AVAILABLE
