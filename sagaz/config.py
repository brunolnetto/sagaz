"""
SagaConfig - Unified configuration for the Saga framework.

Provides a single, type-safe configuration object that wires together:
- Storage backend (for saga state persistence)
- Message broker (for outbox pattern)
- Observability (metrics, tracing, logging)

Example:
    >>> from sagaz import SagaConfig, Saga
    >>> from sagaz.storage import PostgreSQLSagaStorage
    >>> from sagaz.outbox.brokers import KafkaBroker
    >>>
    >>> config = SagaConfig(
    ...     storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    ...     broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    ...     metrics=True,
    ...     tracing=True,
    ...     logging=True,
    ... )
    >>>
    >>> Saga.configure(config)
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     # Storage and listeners automatically configured!
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.listeners import SagaListener
    from sagaz.outbox.brokers.base import BaseBroker
    from sagaz.storage.base import SagaStorage

logger = logging.getLogger(__name__)


@dataclass
class SagaConfig:
    """
    Unified configuration for the Saga framework.

    Provides a clean, type-safe way to configure all saga components in one place.
    Values can be actual instances (recommended) or boolean flags for defaults.

    Attributes:
        storage: Saga state storage backend (PostgreSQL, Redis, Memory)
        broker: Message broker for outbox pattern (Kafka, RabbitMQ, Redis, Memory)
        metrics: Enable metrics collection (True/False or MetricsSagaListener instance)
        tracing: Enable distributed tracing (True/False or TracingSagaListener instance)
        logging: Enable saga logging (True/False or LoggingSagaListener instance)
        default_timeout: Default step timeout in seconds
        default_max_retries: Default retry count for failed steps
        failure_strategy: Default parallel failure strategy

    Example:
        >>> # Minimal config (in-memory, for development)
        >>> config = SagaConfig()
        >>>
        >>> # Production config
        >>> config = SagaConfig(
        ...     storage=PostgreSQLSagaStorage("postgresql://..."),
        ...     broker=KafkaBroker(bootstrap_servers="..."),
        ...     metrics=True,
        ...     tracing=True,
        ... )
    """

    # Storage backend - defaults to in-memory
    storage: SagaStorage | None = None

    # Outbox storage - defaults to same as saga storage for transactional guarantees
    outbox_storage: Any | None = None  # OutboxStorage, but avoiding circular import

    # Message broker for outbox pattern (optional)
    broker: BaseBroker | None = None

    # Observability - can be bool or actual listener instance
    metrics: bool | SagaListener = True
    tracing: bool | SagaListener = False
    logging: bool | SagaListener = True

    # Saga execution defaults
    default_timeout: float = 60.0
    default_max_retries: int = 3
    failure_strategy: str = "FAIL_FAST_WITH_GRACE"

    # Internal: cached listeners list
    _listeners: list[SagaListener] = field(default_factory=list, repr=False)
    _derived_outbox_storage: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize storage and build listeners list."""
        # Default to in-memory storage if not specified
        if self.storage is None:
            from sagaz.storage.memory import InMemorySagaStorage

            self.storage = InMemorySagaStorage()
            logger.debug("Using default InMemorySagaStorage")

        # Handle outbox storage derivation
        self._derive_outbox_storage()

        # Build listeners list from config
        self._listeners = self._build_listeners()

    def _derive_outbox_storage(self) -> None:
        """
        Derive outbox storage from saga storage if not explicitly set.

        For transactional guarantees, outbox storage should ideally use
        the same database as saga storage.
        """
        if self.broker is None:
            # No broker = no outbox needed
            return

        if self.outbox_storage is not None:
            # Explicitly set - use as-is
            self._derived_outbox_storage = self.outbox_storage
            return

        # Broker is set but outbox_storage is not - derive from saga storage
        storage_type = type(self.storage).__name__

        if storage_type == "PostgreSQLSagaStorage":
            # Derive PostgreSQL outbox storage from same connection
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

            conn_string = getattr(self.storage, "connection_string", None)
            if conn_string:
                self._derived_outbox_storage = PostgreSQLOutboxStorage(conn_string)
                logger.warning(
                    "Broker configured without explicit outbox_storage. "
                    "Defaulting to PostgreSQLOutboxStorage with same connection "
                    "for transactional guarantees."
                )
            else:
                self._use_memory_outbox_with_warning()

        elif storage_type == "RedisSagaStorage":
            # Redis doesn't support transactions across saga + outbox
            # Use in-memory with warning
            self._use_memory_outbox_with_warning()

        else:
            # InMemory or unknown - use in-memory outbox
            self._use_memory_outbox_with_warning()

    def _use_memory_outbox_with_warning(self) -> None:
        """Use in-memory outbox storage with a warning."""
        from sagaz.outbox.storage.memory import InMemoryOutboxStorage

        self._derived_outbox_storage = InMemoryOutboxStorage()
        logger.warning(
            "Broker configured without explicit outbox_storage. "
            "Using InMemoryOutboxStorage - events will NOT survive restarts. "
            "For production, set outbox_storage explicitly."
        )

    def _build_listeners(self) -> list[SagaListener]:
        """Build listeners list from configuration."""
        from sagaz.listeners import (
            LoggingSagaListener,
            MetricsSagaListener,
            OutboxSagaListener,
            SagaListener,
            TracingSagaListener,
        )

        listeners: list[SagaListener] = []

        # Logging
        if isinstance(self.logging, SagaListener):
            listeners.append(self.logging)
        elif self.logging:
            listeners.append(LoggingSagaListener())

        # Metrics
        if isinstance(self.metrics, SagaListener):
            listeners.append(self.metrics)
        elif self.metrics:
            listeners.append(MetricsSagaListener())

        # Tracing
        if isinstance(self.tracing, SagaListener):
            listeners.append(self.tracing)
        elif self.tracing:
            listeners.append(TracingSagaListener())

        # Outbox listener (if broker is configured)
        if self.broker is not None and self._derived_outbox_storage is not None:
            listeners.append(OutboxSagaListener(storage=self._derived_outbox_storage))
            logger.debug(
                f"Outbox listener enabled with {type(self._derived_outbox_storage).__name__}"
            )

        return listeners

    @property
    def listeners(self) -> list[SagaListener]:
        """Get configured listeners list."""
        return self._listeners

    def with_storage(self, storage: SagaStorage) -> SagaConfig:
        """Create a new config with different storage (immutable update)."""
        return SagaConfig(
            storage=storage,
            outbox_storage=self.outbox_storage,
            broker=self.broker,
            metrics=self.metrics,
            tracing=self.tracing,
            logging=self.logging,
            default_timeout=self.default_timeout,
            default_max_retries=self.default_max_retries,
            failure_strategy=self.failure_strategy,
        )

    def with_broker(self, broker: BaseBroker, outbox_storage=None) -> SagaConfig:
        """Create a new config with different broker (immutable update)."""
        return SagaConfig(
            storage=self.storage,
            outbox_storage=outbox_storage or self.outbox_storage,
            broker=broker,
            metrics=self.metrics,
            tracing=self.tracing,
            logging=self.logging,
            default_timeout=self.default_timeout,
            default_max_retries=self.default_max_retries,
            failure_strategy=self.failure_strategy,
        )

    @classmethod
    def from_env(cls) -> SagaConfig:
        """
        Create configuration from environment variables.

        Environment variables:
            SAGAZ_STORAGE_URL: Storage connection string (auto-detects type)
            SAGAZ_BROKER_URL: Broker connection string (auto-detects type)
            SAGAZ_METRICS: Enable metrics (true/false)
            SAGAZ_TRACING: Enable tracing (true/false)
            SAGAZ_LOGGING: Enable logging (true/false)
            SAGAZ_TRACING_ENDPOINT: OpenTelemetry collector endpoint

        Example:
            >>> import os
            >>> os.environ["SAGAZ_STORAGE_URL"] = "postgresql://localhost/db"
            >>> os.environ["SAGAZ_BROKER_URL"] = "kafka://localhost:9092"
            >>> config = SagaConfig.from_env()
        """
        import os

        storage = None
        broker = None

        # Parse storage URL
        storage_url = os.environ.get("SAGAZ_STORAGE_URL", "")
        if storage_url:
            storage = cls._parse_storage_url(storage_url)

        # Parse broker URL
        broker_url = os.environ.get("SAGAZ_BROKER_URL", "")
        if broker_url:
            broker = cls._parse_broker_url(broker_url)

        # Parse boolean flags
        def parse_bool(key: str, default: bool = True) -> bool:
            val = os.environ.get(key, "").lower()
            if val in ("true", "1", "yes"):
                return True
            if val in ("false", "0", "no"):
                return False
            return default

        return cls(
            storage=storage,
            broker=broker,
            metrics=parse_bool("SAGAZ_METRICS", True),
            tracing=parse_bool("SAGAZ_TRACING", False),
            logging=parse_bool("SAGAZ_LOGGING", True),
        )

    @staticmethod
    def _parse_storage_url(url: str) -> SagaStorage:
        """Parse storage URL and return appropriate storage instance."""
        if url.startswith(("postgresql://", "postgres://")):
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            return PostgreSQLSagaStorage(url)
        if url.startswith("redis://"):
            from sagaz.storage.redis import RedisSagaStorage

            return RedisSagaStorage(url)
        if url == "memory://" or url == "":
            from sagaz.storage.memory import InMemorySagaStorage

            return InMemorySagaStorage()
        msg = f"Unknown storage URL scheme: {url}"
        raise ValueError(msg)

    @staticmethod
    def _parse_broker_url(url: str) -> BaseBroker:
        """Parse broker URL and return appropriate broker instance."""
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
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker, RabbitMQBrokerConfig

            rmq_config = RabbitMQBrokerConfig(url=url.replace("rabbitmq://", "amqp://"))
            return RabbitMQBroker(rmq_config)
        if url == "memory://" or url == "":
            from sagaz.outbox.brokers.memory import InMemoryBroker

            return InMemoryBroker()
        msg = f"Unknown broker URL scheme: {url}"
        raise ValueError(msg)


# Global configuration singleton
_global_config: SagaConfig | None = None


def get_config() -> SagaConfig:
    """Get the global saga configuration."""
    global _global_config
    if _global_config is None:
        _global_config = SagaConfig()
    return _global_config


def configure(config: SagaConfig) -> None:
    """Set the global saga configuration."""
    global _global_config
    _global_config = config
    logger.info(f"Saga configured: storage={type(config.storage).__name__}")
