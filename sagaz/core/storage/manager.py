"""
Storage Manager - Unified facade for saga and outbox storage.

Provides a single entry point for all storage needs with flexible
backend configuration and simplified lifecycle management.

Usage (same backend for both):
    >>> from sagaz.core.storage import create_storage_manager
    >>>
    >>> # Single URL = same backend for saga and outbox
    >>> manager = create_storage_manager("postgresql://user:pass@localhost/db")
    >>> await manager.initialize()
    >>> await manager.saga.save_saga_state(...)
    >>> await manager.outbox.insert(event)

Usage (different backends):
    >>> # Separate URLs = different backends
    >>> manager = create_storage_manager(
    ...     saga_url="postgresql://localhost/saga_db",
    ...     outbox_url="redis://localhost:6379",
    ... )
    >>> await manager.initialize()
    >>> # saga uses PostgreSQL, outbox uses Redis
"""

from typing import TYPE_CHECKING, Any, cast

from sagaz.core.storage._manager_backends import _StorageBackendInitMixin
from sagaz.core.storage._manager_base import BaseStorageManager

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import OutboxStorage, SagaStorage


class StorageManager(_StorageBackendInitMixin, BaseStorageManager):
    """
    Flexible storage manager supporting any backend combination.

    Can use the same backend for both saga and outbox (shared pooling),
    or different backends for each (hybrid mode).

    Usage (same backend):
        >>> manager = StorageManager(url="postgresql://localhost/db")
        >>> await manager.initialize()

    Usage (different backends):
        >>> manager = StorageManager(
        ...     saga_url="postgresql://localhost/saga_db",
        ...     outbox_url="redis://localhost:6379",
        ... )
        >>> await manager.initialize()
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        saga_url: str | None = None,
        outbox_url: str | None = None,
        **kwargs,
    ):
        """
        Initialize storage manager.

        Args:
            url: Single URL for both saga and outbox (same backend).
                 If provided, saga_url and outbox_url are ignored.
            saga_url: URL for saga storage (different backend mode).
            outbox_url: URL for outbox storage (different backend mode).
            **kwargs: Additional backend-specific configuration.

        Examples:
            # Same backend (shared connection)
            StorageManager(url="postgresql://localhost/db")

            # Different backends (hybrid)
            StorageManager(
                saga_url="postgresql://localhost/saga_db",
                outbox_url="redis://localhost:6379",
            )

            # Memory (default)
            StorageManager()
        """
        self._unified_url = url
        self._saga_url = saga_url if url is None else url
        self._outbox_url = outbox_url if url is None else url
        self._kwargs = kwargs

        # Determine mode
        self._is_hybrid = (
            url is None
            and saga_url is not None
            and outbox_url is not None
            and self._get_backend_type(saga_url) != self._get_backend_type(outbox_url)
        )

        # Storage instances (created during initialize)
        self._saga_storage: SagaStorage | None = None
        self._outbox_storage: OutboxStorage | None = None
        self._shared_pool: Any | None = None  # For backends that support pooling

    @staticmethod
    def _get_backend_type(url: str | None) -> str:
        """Detect backend type from URL."""
        if not url or url == "memory://":
            return "memory"
        if url.startswith(("postgresql://", "postgres://")):
            return "postgresql"
        if url.startswith("redis://"):
            return "redis"
        if (
            url.startswith("sqlite://")
            or url.endswith((".db", ".sqlite", ".sqlite3"))
            or url == ":memory:"
        ):
            return "sqlite"
        return "unknown"

    @property
    def saga(self) -> "SagaStorage":
        """Get saga storage instance."""
        if self._saga_storage is None:
            msg = "Storage not initialized. Call initialize() first."
            raise RuntimeError(msg)
        return self._saga_storage

    @property
    def outbox(self) -> "OutboxStorage":
        """Get outbox storage instance."""
        if self._outbox_storage is None:
            msg = "Storage not initialized. Call initialize() first."
            raise RuntimeError(msg)
        return self._outbox_storage

    @property
    def is_hybrid(self) -> bool:
        """True if using different backends for saga and outbox."""
        return self._is_hybrid

    async def initialize(self) -> None:
        """Initialize storage backends."""
        saga_type = self._get_backend_type(self._saga_url)
        outbox_type = self._get_backend_type(self._outbox_url)

        if saga_type == outbox_type and not self._is_hybrid:
            # Same backend - can share connections
            await self._initialize_unified(saga_type)
        else:
            # Different backends - initialize separately
            await self._initialize_hybrid(saga_type, outbox_type)

    async def close(self) -> None:
        """Close all connections."""
        # Close shared pool if exists (PostgreSQL/Redis unified mode)
        if self._shared_pool is not None:
            if hasattr(self._shared_pool, "close"):
                if hasattr(self._shared_pool, "wait_closed"):
                    # asyncpg pool
                    await self._shared_pool.close()
                    await self._shared_pool.wait_closed()
                else:
                    # redis connection
                    await self._shared_pool.close()
            self._shared_pool = None

        # Always close individual storages (they may have their own connections)
        if self._saga_storage and hasattr(self._saga_storage, "close"):
            await self._saga_storage.close()
        if self._outbox_storage and hasattr(self._outbox_storage, "close"):
            await self._outbox_storage.close()

        self._saga_storage = None
        self._outbox_storage = None

    async def health_check(self) -> dict[str, Any]:
        """Check health of all storage components."""
        saga_health: dict[str, Any] = {"status": "unhealthy"}
        outbox_health: dict[str, Any] = {"status": "unhealthy"}

        if self._saga_storage:
            try:
                if hasattr(self._saga_storage, "health_check"):
                    result = await self._saga_storage.health_check()  # type: ignore[assignment]
                    saga_health = self._normalize_health_result(result)
                else:
                    saga_health = {"status": "healthy"}
            except Exception as e:
                saga_health = {"status": "unhealthy", "error": str(e)}

        if self._outbox_storage:
            try:
                if hasattr(self._outbox_storage, "health_check"):
                    result = await self._outbox_storage.health_check()  # type: ignore[assignment]
                    outbox_health = self._normalize_health_result(result)
                else:
                    outbox_health = {"status": "healthy"}
            except Exception as e:
                outbox_health = {"status": "unhealthy", "error": str(e)}

        # Normalize status values for comparison
        saga_status = saga_health.get("status", "unhealthy")
        outbox_status = outbox_health.get("status", "unhealthy")

        is_healthy = saga_status in ("healthy", "HEALTHY") and outbox_status in (
            "healthy",
            "HEALTHY",
        )

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "mode": "hybrid" if self._is_hybrid else "unified",
            "saga_backend": self._get_backend_type(self._saga_url),
            "outbox_backend": self._get_backend_type(self._outbox_url),
            "saga": saga_health,
            "outbox": outbox_health,
        }

    @staticmethod
    def _normalize_health_result(result: Any) -> dict[str, Any]:
        """Convert health check result to dict format."""
        # Handle HealthCheckResult objects
        if hasattr(result, "to_dict"):
            return result.to_dict()  # type: ignore[no-any-return]
        if hasattr(result, "status"):
            # HealthCheckResult object without to_dict
            status_val = (
                result.status.value if hasattr(result.status, "value") else str(result.status)
            )
            return {"status": status_val}
        if isinstance(result, dict):
            return result  # type: ignore[return-value]
        return {"status": "healthy"}


# Backend configuration for explicit backend mode
_BACKEND_CONFIGS = {
    "memory": {"requires_url": False, "default_url": None},
    "postgresql": {"requires_url": True, "default_url": None},
    "postgres": {"requires_url": True, "default_url": None},
    "redis": {"requires_url": False, "default_url": "redis://localhost:6379"},
    "sqlite": {"requires_url": False, "default_url": ":memory:"},
}


def create_storage_manager(
    url: str | None = None,
    *,
    saga_url: str | None = None,
    outbox_url: str | None = None,
    backend: str | None = None,
    **kwargs,
) -> StorageManager:
    """
    Create a storage manager with flexible backend configuration.

    Supports three modes:
    1. Unified: Single URL for both saga and outbox (shared connection pool)
    2. Hybrid: Different URLs/backends for saga and outbox
    3. Default: In-memory storage for testing

    Args:
        url: Single URL for both saga and outbox storage.
             Auto-detects backend from scheme (postgresql://, redis://, etc.)
        saga_url: URL for saga storage only (enables hybrid mode).
        outbox_url: URL for outbox storage only (enables hybrid mode).
        backend: Explicit backend type (overrides URL detection).
                 Options: "memory", "postgresql", "redis", "sqlite"
        **kwargs: Backend-specific configuration (pool sizes, etc.)

    Returns:
        StorageManager instance (not yet initialized - call initialize())

    Raises:
        ValueError: If URL scheme is unknown or required parameters are missing.
    """
    # Handle explicit backend override
    if backend:
        return _create_with_explicit_backend(backend, url, saga_url, outbox_url, **kwargs)

    # Check for hybrid mode
    if saga_url is not None or outbox_url is not None:
        return StorageManager(saga_url=saga_url, outbox_url=outbox_url, **kwargs)

    # Validate URL scheme if provided
    _validate_url_scheme(url)

    # Single URL mode (unified backend)
    return StorageManager(url=url, **kwargs)


def _create_with_explicit_backend(
    backend: str, url: str | None, saga_url: str | None, outbox_url: str | None, **kwargs
) -> StorageManager:
    """Create storage manager with explicit backend type."""
    backend = backend.lower()

    if backend not in _BACKEND_CONFIGS:
        msg = f"Unknown backend: {backend}"
        raise ValueError(msg)

    config = cast(dict[str, Any], _BACKEND_CONFIGS[backend])

    if config["requires_url"] and not url and not saga_url:
        msg = f"url is required for {backend} backend"
        raise ValueError(msg)

    if backend == "memory":
        return StorageManager()

    effective_url = url or cast(str | None, config["default_url"])
    return StorageManager(url=effective_url, saga_url=saga_url, outbox_url=outbox_url, **kwargs)


def _validate_url_scheme(url: str | None) -> None:
    """Validate that URL has a recognized scheme."""
    if url is None or url == "memory://" or url == "":
        return

    detected = StorageManager._get_backend_type(url)
    if detected == "unknown":
        msg = (
            f"Cannot determine backend from URL: {url}. "
            "Use postgresql://, redis://, sqlite://, or memory://"
        )
        raise ValueError(msg)
