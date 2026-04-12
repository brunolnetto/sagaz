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
    >>> from sagaz.core.storage import create_storage_manager
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
    >>> from sagaz.core.storage import PostgreSQLSagaStorage
    >>> from sagaz.core.outbox.brokers import KafkaBroker
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
    from sagaz.core.outbox.brokers.base import BaseBroker
    from sagaz.core.storage.base import SagaStorage

from sagaz.core.config._broker import BrokerConfigManager
from sagaz.core.config._storage import StorageConfigManager

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

    # NEW: StorageManager for unified storage access
    # (alternative to storage + outbox_storage)
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
                    "Use storage_manager for unified storage, or "
                    "storage/outbox_storage separately."
                )
                raise ValueError(msg)
            if self.outbox_storage is not None:
                msg = (
                    "Cannot specify both 'storage_manager' and 'outbox_storage'. "
                    "Use storage_manager for unified storage, or "
                    "storage/outbox_storage separately."
                )
                raise ValueError(msg)
            self.storage, self._storage_manager = StorageConfigManager.setup_from_manager(
                self.storage, self.storage_manager
            )
            # Extract outbox storage from the manager if available
            try:
                self.outbox_storage = self.storage_manager.outbox
            except RuntimeError:
                # Manager not initialized - outbox_storage will be derived later
                self.outbox_storage = None
        else:
            # Default to in-memory storage if not specified
            if self.storage is None:
                from sagaz.core.storage.memory import InMemorySagaStorage

                self.storage = InMemorySagaStorage()
                logger.debug("Using default InMemorySagaStorage")

        # Handle outbox storage derivation
        self._derived_outbox_storage = StorageConfigManager.derive_outbox_storage(
            self.storage, self.broker, self.outbox_storage
        )

        # Build listeners list from config
        self._listeners = self._build_listeners()

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
    def _storage_from_env(cls, env: object) -> object:
        """Construct a storage backend from an env-dict (backward compat helper)."""
        return StorageConfigManager.from_env(env)

    @classmethod
    def _broker_from_env(cls, env: object) -> object:
        """Construct a broker backend from an env-dict (backward compat helper)."""
        return BrokerConfigManager.from_env(env)

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

        storage = StorageConfigManager.from_env(env)
        broker = BrokerConfigManager.from_env(env)

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

        # Build components using manager methods
        storage = StorageConfigManager.from_config_dict(storage_data)
        broker = BrokerConfigManager.from_config_dict(broker_data)

        # Build Config
        return cls(
            storage=storage,
            broker=broker,
            metrics=obs_data.get("prometheus", {}).get("enabled", True),
            tracing=obs_data.get("tracing", {}).get("enabled", False),
            logging=obs_data.get("logging", {}).get("enabled", True),
        )

    # Backward compatibility: delegate to submodule methods
    @staticmethod
    def _parse_storage_url(url: str):
        """Backward compatible: parse storage URL and return storage instance."""
        return StorageConfigManager._parse_storage_url(url)

    @staticmethod
    def _parse_broker_url(url: str):
        """Backward compatible: parse broker URL and return broker instance."""
        return BrokerConfigManager._parse_broker_url(url)

    def _setup_from_manager(self):
        """Backward compatible: setup from storage manager (instance method)."""
        storage, storage_manager = StorageConfigManager.setup_from_manager(
            self.storage, self.storage_manager
        )
        self.storage = storage
        self._storage_manager = storage_manager


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
