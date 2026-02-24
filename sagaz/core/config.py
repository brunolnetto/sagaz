"""
SagaConfig - Unified configuration for the Saga framework.

Provides a single, type-safe configuration object that wires together:
- Storage backend (for saga state persistence)
- Message broker (for outbox pattern)
- Observability (metrics, tracing, logging)

IMPORTANT: You must choose ONE storage approach:
  - Option 1: Use `storage_manager` for unified saga + outbox storage
  - Option 2: Use `storage` and optionally `outbox_storage` separately
  Mixing both approaches will raise a ValueError.

Example (Option 1 - unified StorageManager, RECOMMENDED):
    >>> from sagaz import SagaConfig, configure
    >>> from sagaz.storage import create_storage_manager
    >>>
    >>> # StorageManager provides unified access to saga + outbox storage
    >>> # with shared connection pooling
    >>> manager = create_storage_manager("postgresql://localhost/db")
    >>> await manager.initialize()
    >>>
    >>> config = SagaConfig(
    ...     storage_manager=manager,  # Replaces storage + outbox_storage
    ...     broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    ...     metrics=True,
    ... )
    >>>
    >>> configure(config)

Example (Option 2 - separate storage instances):
    >>> from sagaz import SagaConfig, configure
    >>> from sagaz.storage import PostgreSQLSagaStorage
    >>> from sagaz.outbox.brokers import KafkaBroker
    >>>
    >>> config = SagaConfig(
    ...     storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    ...     broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    ...     metrics=True,
    ... )
    >>>
    >>> configure(config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.listeners import SagaListener
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

    # NEW: StorageManager for unified storage access (alternative to storage + outbox_storage)
    # If provided, storage and outbox_storage are extracted from the manager
    storage_manager: Any | None = None  # StorageManager, avoiding circular import

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
    _storage_manager: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize storage and build listeners list."""
        # Validate: cannot mix storage_manager with storage/outbox_storage
        if self.storage_manager is not None:
            if self.storage is not None:
                msg = (
                    "Cannot specify both 'storage_manager' and 'storage'. "
                    "Use storage_manager for unified storage, or storage/outbox_storage separately."
                )
                raise ValueError(msg)
            if self.outbox_storage is not None:
                msg = (
                    "Cannot specify both 'storage_manager' and 'outbox_storage'. "
                    "Use storage_manager for unified storage, or storage/outbox_storage separately."
                )
                raise ValueError(msg)
            self._setup_from_manager()
        else:
            # Default to in-memory storage if not specified
            if self.storage is None:
                from sagaz.storage.memory import InMemorySagaStorage

                self.storage = InMemorySagaStorage()
                logger.debug("Using default InMemorySagaStorage")

        # Handle outbox storage derivation
        self._derive_outbox_storage()

        # Build listeners list from config
        self._listeners = self._build_listeners()

    def _setup_from_manager(self) -> None:
        """Extract storage instances from StorageManager."""
        manager = self.storage_manager

        # Check if manager is initialized
        try:
            if manager is not None:
                self.storage = manager.saga
                if self.outbox_storage is None:
                    self.outbox_storage = manager.outbox
            self._storage_manager = manager
            logger.info("Using StorageManager for unified storage access")
        except RuntimeError:
            # Manager not initialized - store reference and use lazy access
            # Manager not initialized - store reference and use lazy access
            import warnings

            warnings.warn(
                "StorageManager provided but not initialized. "
                "Call await storage_manager.initialize() before using Saga.",
                RuntimeWarning,
                stacklevel=2,
            )
            self._storage_manager = manager
            # Fall back to defaults for now
            if self.storage is None:
                from sagaz.storage.memory import InMemorySagaStorage

                self.storage = InMemorySagaStorage()

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
            from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

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
        from sagaz.storage.backends.memory.outbox import InMemoryOutboxStorage

        self._derived_outbox_storage = InMemoryOutboxStorage()
        logger.warning(
            "Broker configured without explicit outbox_storage. "
            "Using InMemoryOutboxStorage - events will NOT survive restarts. "
            "For production, set outbox_storage explicitly."
        )

    def _build_listeners(self) -> list[SagaListener]:
        """Build listeners list from configuration."""
        from sagaz.core.listeners import (
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
    def from_env(cls, load_dotenv: bool = True) -> SagaConfig:
        """
        Create configuration from environment variables.

        Environment variables:
            SAGAZ_STORAGE_URL: Storage connection string (auto-detects type)
            SAGAZ_STORAGE_TYPE: Storage type (postgresql, redis, memory)
            SAGAZ_STORAGE_HOST, PORT, DB, USER, PASSWORD: Individual components
            SAGAZ_BROKER_URL: Broker connection string (auto-detects type)
            SAGAZ_BROKER_TYPE: Broker type (kafka, rabbitmq, redis, memory)
            SAGAZ_METRICS: Enable metrics (true/false)
            SAGAZ_TRACING: Enable tracing (true/false)
            SAGAZ_LOGGING: Enable logging (true/false)
            SAGAZ_TRACING_ENDPOINT: OpenTelemetry collector endpoint

        Args:
            load_dotenv: If True, loads .env file before reading variables

        Example:
            >>> import os
            >>> os.environ["SAGAZ_STORAGE_URL"] = "postgresql://localhost/db"
            >>> os.environ["SAGAZ_BROKER_URL"] = "kafka://localhost:9092"
            >>> config = SagaConfig.from_env()
        """
        import os

        from sagaz.core.env import get_env

        env = get_env()
        if load_dotenv:
            env.load()

        storage = None
        broker = None

        # Parse storage - try URL first, then build from components
        storage_url = env.get("SAGAZ_STORAGE_URL", "")
        if storage_url:
            storage = cls._parse_storage_url(storage_url)
        else:
            storage_type = env.get("SAGAZ_STORAGE_TYPE", "memory")
            if storage_type == "postgresql":
                host = env.get("SAGAZ_STORAGE_HOST", "localhost")
                port = env.get("SAGAZ_STORAGE_PORT", "5432")
                db = env.get("SAGAZ_STORAGE_DB", "sagaz")
                user = env.get("SAGAZ_STORAGE_USER", "postgres")
                password = env.get("SAGAZ_STORAGE_PASSWORD", "postgres")
                storage_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
                storage = cls._parse_storage_url(storage_url)
            elif storage_type == "redis":
                redis_url = env.get("SAGAZ_STORAGE_URL", "redis://localhost:6379/0")
                storage = cls._parse_storage_url(redis_url)

        # Parse broker - try URL first, then build from components
        broker_url = env.get("SAGAZ_BROKER_URL", "")
        if broker_url:
            broker = cls._parse_broker_url(broker_url)
        else:
            broker_type = env.get("SAGAZ_BROKER_TYPE", "")
            if broker_type == "kafka":
                host = env.get("SAGAZ_BROKER_HOST", "localhost")
                port = env.get("SAGAZ_BROKER_PORT", "9092")
                broker_url = f"kafka://{host}:{port}"
                broker = cls._parse_broker_url(broker_url)
            elif broker_type == "rabbitmq":
                host = env.get("SAGAZ_BROKER_HOST", "localhost")
                port = env.get("SAGAZ_BROKER_PORT", "5672")
                user = env.get("SAGAZ_BROKER_USER", "guest")
                password = env.get("SAGAZ_BROKER_PASSWORD", "guest")
                broker_url = f"amqp://{user}:{password}@{host}:{port}/"
                broker = cls._parse_broker_url(broker_url)
            elif broker_type == "redis":
                redis_url = env.get("SAGAZ_BROKER_URL", "redis://localhost:6379/1")
                broker = cls._parse_broker_url(redis_url)

        return cls(
            storage=storage,
            broker=broker,
            metrics=env.get_bool("SAGAZ_METRICS", True),
            tracing=env.get_bool("SAGAZ_TRACING", False),
            logging=env.get_bool("SAGAZ_LOGGING", True),
        )

    @classmethod
    def from_file(cls, file_path: str | Path, substitute_env: bool = True) -> SagaConfig:
        """
        Load configuration from a YAML or JSON file.

        Supports environment variable substitution using ${VAR} syntax.

        Args:
            file_path: Path to the configuration file (e.g., 'sagaz.yaml')
            substitute_env: If True, substitute environment variables in config

        Example:
            >>> config = SagaConfig.from_file("sagaz.yaml")

            # In sagaz.yaml:
            # storage:
            #   connection:
            #     host: ${SAGAZ_STORAGE_HOST:-localhost}
            #     password: ${SAGAZ_STORAGE_PASSWORD:?Password required}
        """
        import yaml

        from sagaz.core.env import get_env

        path = Path(file_path)
        if not path.exists():
            msg = f"Configuration file not found: {file_path}"
            raise FileNotFoundError(msg)

        with path.open() as f:
            data = yaml.safe_load(f)

        if not data:
            return cls()

        # Substitute environment variables in the config
        if substitute_env:
            env = get_env()
            env.load()  # Load .env if exists
            data = env.substitute_dict(data)

        # Extract sections
        storage_data = data.get("storage", {})
        broker_data = data.get("broker", {})
        obs_data = data.get("observability", {})

        # Build components using helper methods
        storage = cls._build_storage_from_config(storage_data)
        broker = cls._build_broker_from_config(broker_data)

        # Build Config
        return cls(
            storage=storage,
            broker=broker,
            metrics=obs_data.get("prometheus", {}).get("enabled", True),
            tracing=obs_data.get("tracing", {}).get("enabled", False),
            logging=obs_data.get("logging", {}).get("enabled", True),
        )

    @classmethod
    def _build_storage_from_config(cls, storage_data: dict) -> SagaStorage | None:
        """Build storage instance from config dict."""
        if not storage_data:
            return None

        s_type = storage_data.get("type", "postgresql").lower()
        conn = storage_data.get("connection", {})

        if s_type == "postgresql":
            from sagaz.storage.postgresql import PostgreSQLSagaStorage

            url = conn.get("url") or cls._build_postgres_url(conn)
            return PostgreSQLSagaStorage(url)

        if s_type == "redis":
            from sagaz.storage.redis import RedisSagaStorage

            url = conn.get("url", "redis://localhost:6379")
            return RedisSagaStorage(url)

        return None

    @staticmethod
    def _build_postgres_url(conn: dict) -> str:
        """Build PostgreSQL URL from connection components."""
        user = conn.get("user", "postgres")
        pwd = conn.get("password", "postgres")
        host = conn.get("host", "localhost")
        port = conn.get("port", 5432)
        db = conn.get("database", "sagaz")
        return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

    @classmethod
    def _build_broker_from_config(cls, broker_data: dict) -> BaseBroker | None:
        """Build broker instance from config dict."""
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
            from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker, RabbitMQBrokerConfig

            user = conn.get("user", "guest")
            pwd = conn.get("password", "guest")
            host = conn.get("host", "localhost")
            port = conn.get("port", 5672)
            url = f"amqp://{user}:{pwd}@{host}:{port}/"
            rmq_config = RabbitMQBrokerConfig(url=url)
            return RabbitMQBroker(rmq_config)

        return None

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
