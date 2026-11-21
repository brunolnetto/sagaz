"""SagaConfig and the process-wide configuration singleton."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.listeners import SagaListener
    from sagaz.core.outbox.brokers.base import BaseBroker
    from sagaz.core.storage.base import SagaStorage

from sagaz.core.config._broker import BrokerConfigManager, EnvLike
from sagaz.core.config._storage import StorageConfigManager

logger = logging.getLogger("sagaz.core.config")


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
    # Multi-tenancy (ADR-020): resolves tenant ids given to Saga.run(tenant_context=...)
    tenant_registry: Any | None = None  # TenantRegistry, avoiding circular import

    # Event sourcing (ADR-033): defaults for sagas whose Meta does not set them.
    # "event_sourced" records every state change in event_store (a
    # SagaEventStore or a URL such as "postgresql://...").
    storage_strategy: str = "snapshot"
    event_store: Any | None = None  # SagaEventStore | str, avoiding circular import
    snapshot_threshold: int = 50

    # Unified saga log (ADR-041): "unified" records every saga on saga_log (a
    # SagaLogStore or a URL), as participant (the service name). "classic" (the
    # default) keeps a table per concern; its former name "legacy" is accepted (#578).
    storage_layout: str = "classic"
    saga_log: Any | None = None  # SagaLogStore | str
    participant: str | None = None

    # Multi-region (ADR-034): runs steps declared with region= on that region's
    # workers. A MultiRegionCoordinator, or built from the sagaz.yaml regions block.
    regions: Any | None = None

    default_timeout: float = 60.0
    default_max_retries: int = 3
    failure_strategy: str = "FAIL_FAST_WITH_GRACE"

    # A failure to save the saga state raises SagaPersistenceError (#534); True logs a
    # warning instead and lets the saga go on (the behavior before 2.4).
    tolerate_persistence_errors: bool = False

    # Listeners added to the logging, metrics, tracing and outbox ones (#538). A saga
    # class's ``listeners`` attribute replaces them all instead.
    extra_listeners: list[Any] = field(default_factory=list)

    # StateChart phase 2 (ADR-040, #190): imperative sagas run on a chart with one
    # region per step, whose configuration says where every step is. Off by default.
    use_step_statechart: bool = False

    # Internal: cached listeners list
    _listeners: list[SagaListener] = field(default_factory=list, repr=False)
    _derived_outbox_storage: Any = field(default=None, repr=False)
    _storage_manager: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize storage and build listeners list."""
        if self.storage_layout == "legacy":  # the classic layout's former name (#578)
            self.storage_layout = "classic"
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

        # Listeners added alongside the built-in ones (#538).
        listeners.extend(self.extra_listeners)

        return listeners

    @property
    def listeners(self) -> list[SagaListener]:
        """Get configured listeners list."""
        return self._listeners

    def with_storage(self, storage: SagaStorage) -> SagaConfig:
        """Create a new config with different storage (immutable update)."""
        return self._replace(storage=storage)

    def with_broker(self, broker: BaseBroker, outbox_storage=None) -> SagaConfig:
        """Create a new config with different broker (immutable update)."""
        return self._replace(broker=broker, outbox_storage=outbox_storage or self.outbox_storage)

    def _replace(self, **changes: Any) -> SagaConfig:
        """A copy with ``changes``, keeping every other field (#552).

        The copy uses the concrete storage, not the ``storage_manager`` it may have
        come from (a config cannot take both).
        """
        values = {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if f.init and not f.name.startswith("_")
        }
        values["storage_manager"] = None
        values.update(changes)
        return SagaConfig(**values)

    @classmethod
    def _storage_from_env(cls, env: EnvLike) -> object:
        """Construct a storage backend from an env-dict (backward compat helper)."""
        return StorageConfigManager.from_env(env)

    @classmethod
    def _broker_from_env(cls, env: EnvLike) -> object:
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

        with path.open(encoding="utf-8") as f:
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
        regions = None
        if data.get("regions"):
            from sagaz.core.regions._config import coordinator_from_config

            regions = coordinator_from_config(data["regions"])

        # Build Config
        return cls(
            storage=storage,
            broker=broker,
            regions=regions,
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
