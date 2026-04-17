"""Storage backend configuration management.

Handles initialization, validation, and construction of storage backends
from various sources (environment, files, URLs).
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.storage.base import SagaStorage

logger = logging.getLogger(__name__)


class StorageConfigManager:
    """Manages storage backend configuration and initialization."""

    @staticmethod
    def setup_from_manager(storage: Any, storage_manager: Any) -> tuple[Any, Any]:
        """Extract storage instances from StorageManager.

        Args:
            storage: Current storage value
            storage_manager: StorageManager instance (for unified storage)

        Returns:
            Tuple of (storage, _storage_manager_ref) for attribute assignment
        """
        manager = storage_manager

        # Check if manager is initialized
        try:
            if manager is not None:
                storage = manager.saga
                # outbox_storage will be derived from manager
            manager_ref = manager
            logger.info("Using StorageManager for unified storage access")
        except RuntimeError:
            # Manager not initialized - store reference and use lazy access
            import warnings

            warnings.warn(
                "StorageManager provided but not initialized. "
                "Call await storage_manager.initialize() before using Saga.",
                RuntimeWarning,
                stacklevel=3,
            )
            manager_ref = manager
            # Fall back to defaults for now
            if storage is None:
                from sagaz.core.storage.memory import InMemorySagaStorage

                storage = InMemorySagaStorage()

        return storage, manager_ref

    @staticmethod
    def derive_outbox_storage(storage: Any, broker: Any, outbox_storage: Any) -> Any:
        """Derive outbox storage from saga storage if not explicitly set.

        For transactional guarantees, outbox storage should ideally use
        the same database as saga storage.

        Args:
            storage: Saga storage backend
            broker: Message broker (if None, no outbox needed)
            outbox_storage: Explicitly set outbox storage (if any)

        Returns:
            Derived or explicit outbox storage instance
        """
        if broker is None:
            # No broker = no outbox needed
            return None

        if outbox_storage is not None:
            # Explicitly set - use as-is
            return outbox_storage

        # Broker is set but outbox_storage is not - derive from saga storage
        storage_type = type(storage).__name__

        if storage_type == "PostgreSQLSagaStorage":
            # Derive PostgreSQL outbox storage from same connection
            from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

            conn_string = getattr(storage, "connection_string", None)
            if conn_string:
                derived = PostgreSQLOutboxStorage(conn_string)
                logger.warning(
                    "Broker configured without explicit outbox_storage. "
                    "Defaulting to PostgreSQLOutboxStorage with same connection "
                    "for transactional guarantees."
                )
                return derived
            return StorageConfigManager._use_memory_outbox_with_warning()

        if storage_type == "RedisSagaStorage":
            # Redis doesn't support transactions across saga + outbox
            # Use in-memory with warning
            return StorageConfigManager._use_memory_outbox_with_warning()

        # InMemory or unknown - use in-memory outbox
        return StorageConfigManager._use_memory_outbox_with_warning()

    @staticmethod
    def _use_memory_outbox_with_warning() -> Any:
        """Use in-memory outbox storage with a warning."""
        from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

        logger.warning(
            "Broker configured without explicit outbox_storage. "
            "Using InMemoryOutboxStorage - events will NOT survive restarts. "
            "For production, set outbox_storage explicitly."
        )
        return InMemoryOutboxStorage()

    @classmethod
    def from_env(cls, env: Any) -> Any:
        """Construct a storage backend descriptor from environment variables.

        Checks SAGAZ_STORAGE_URL first; falls back to
        SAGAZ_STORAGE_TYPE + individual host/port/db/user/password vars.
        Returns None when no storage is configured.

        Args:
            env: Environment configuration object

        Returns:
            Storage backend instance or None
        """
        storage_url = env.get("SAGAZ_STORAGE_URL", "")
        if storage_url:
            return cls._parse_storage_url(storage_url)

        storage_type = env.get("SAGAZ_STORAGE_TYPE", "memory")
        if storage_type == "postgresql":
            host = env.get("SAGAZ_STORAGE_HOST", "localhost")
            port = env.get("SAGAZ_STORAGE_PORT", "5432")
            db = env.get("SAGAZ_STORAGE_DB", "sagaz")
            user = env.get("SAGAZ_STORAGE_USER", "postgres")
            password = env.get("SAGAZ_STORAGE_PASSWORD", "postgres")
            url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
            return cls._parse_storage_url(url)
        if storage_type == "redis":
            redis_url = env.get("SAGAZ_STORAGE_URL")
            if redis_url is None:
                redis_url = "redis://localhost:6379/0"
            return cls._parse_storage_url(redis_url)
        return None

    @classmethod
    def from_config_dict(cls, storage_data: dict) -> "SagaStorage | None":
        """Build storage instance from configuration dictionary.

        Args:
            storage_data: Dictionary with 'type' and 'connection' keys

        Returns:
            Storage instance or None if no storage configured
        """
        if not storage_data:
            return None

        s_type = storage_data.get("type", "postgresql").lower()
        conn = storage_data.get("connection", {})

        if s_type == "postgresql":
            from sagaz.core.storage.postgresql import PostgreSQLSagaStorage

            url = conn.get("url") or cls._build_postgres_url(conn)
            return PostgreSQLSagaStorage(url)

        if s_type == "redis":
            from sagaz.core.storage.redis import RedisSagaStorage

            url = conn.get("url", "redis://localhost:6379")
            return RedisSagaStorage(url)

        return None

    @staticmethod
    def _build_postgres_url(conn: dict) -> str:
        """Build PostgreSQL URL from connection components.

        Args:
            conn: Connection dict with host, port, user, password, database

        Returns:
            PostgreSQL connection URL
        """
        user = conn.get("user", "postgres")
        pwd = conn.get("password", "postgres")
        host = conn.get("host", "localhost")
        port = conn.get("port", 5432)
        db = conn.get("database", "sagaz")
        return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

    @staticmethod
    def _parse_storage_url(url: str) -> "SagaStorage":
        """Parse storage URL and return appropriate storage instance.

        Args:
            url: Storage connection URL (postgresql://, redis://, memory://)

        Returns:
            Storage backend instance

        Raises:
            ValueError: If URL scheme is unknown
        """
        if url.startswith(("postgresql://", "postgres://")):
            from sagaz.core.storage.postgresql import PostgreSQLSagaStorage

            return PostgreSQLSagaStorage(url)
        if url.startswith("redis://"):
            from sagaz.core.storage.redis import RedisSagaStorage

            return RedisSagaStorage(url)
        if url in ("memory://", ""):
            from sagaz.core.storage.memory import InMemorySagaStorage

            return InMemorySagaStorage()
        msg = f"Unknown storage URL scheme: {url}"
        raise ValueError(msg)
