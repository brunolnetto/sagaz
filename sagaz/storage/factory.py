"""
Storage Factory - Unified API for creating storage backends.

This module provides a user-friendly factory function for creating storage
backends without needing to import specific storage classes directly.

Supports both saga storage and outbox storage from a unified interface.

Usage:
    >>> from sagaz.storage import create_storage

    # Create saga storage
    >>> saga_storage = create_storage("redis", storage_type="saga")

    # Create outbox storage
    >>> outbox_storage = create_storage("redis", storage_type="outbox")

    # Create both at once
    >>> saga, outbox = create_storage("postgresql", storage_type="both")
"""

from typing import Any, Literal, cast

from sagaz.core.exceptions import MissingDependencyError
from sagaz.storage.backends.memory import InMemorySagaStorage
from sagaz.storage.base import SagaStorage

StorageType = Literal["saga", "outbox", "both"]


def _create_redis_saga_storage(kwargs: dict) -> SagaStorage:
    """Create Redis saga storage instance."""
    from sagaz.storage.backends.redis import RedisSagaStorage

    return RedisSagaStorage(
        redis_url=kwargs.get("redis_url", "redis://localhost:6379"),
        key_prefix=kwargs.get("key_prefix", "saga:"),
        default_ttl=kwargs.get("default_ttl"),
    )


def _create_redis_outbox_storage(kwargs: dict):
    """Create Redis outbox storage instance."""
    from sagaz.storage.backends.redis import RedisOutboxStorage

    return RedisOutboxStorage(
        redis_url=kwargs.get("redis_url", "redis://localhost:6379"),
        prefix=kwargs.get("prefix", "sagaz:outbox"),
        consumer_group=kwargs.get("consumer_group", "sagaz-workers"),
    )


def _create_postgresql_saga_storage(kwargs: dict) -> SagaStorage:
    """Create PostgreSQL saga storage instance."""
    connection_string = kwargs.get("connection_string")
    if not connection_string:
        msg = (
            "PostgreSQL backend requires a connection_string.\n"
            "Example: create_storage('postgresql', connection_string='postgresql://user:pass@localhost/db')"
        )
        raise ValueError(msg)
    from sagaz.storage.backends.postgresql import PostgreSQLSagaStorage

    return PostgreSQLSagaStorage(
        connection_string=connection_string,
        pool_min_size=kwargs.get("pool_min_size", 5),
        pool_max_size=kwargs.get("pool_max_size", 20),
    )


def _create_postgresql_outbox_storage(kwargs: dict):
    """Create PostgreSQL outbox storage instance."""
    connection_string = kwargs.get("connection_string")
    if not connection_string:
        msg = (
            "PostgreSQL backend requires a connection_string.\n"
            "Example: create_storage('postgresql', connection_string='postgresql://user:pass@localhost/db', storage_type='outbox')"
        )
        raise ValueError(msg)
    from sagaz.storage.backends.postgresql import PostgreSQLOutboxStorage

    return PostgreSQLOutboxStorage(
        connection_string=connection_string,
        pool_min_size=kwargs.get("pool_min_size", 5),
        pool_max_size=kwargs.get("pool_max_size", 20),
    )


def _create_memory_outbox_storage(kwargs: dict):
    """Create in-memory outbox storage instance."""
    from sagaz.storage.backends.memory import InMemoryOutboxStorage

    return InMemoryOutboxStorage()


def _create_sqlite_saga_storage(kwargs: dict):
    """Create SQLite saga storage instance."""
    from sagaz.storage.backends.sqlite import SQLiteSagaStorage

    return SQLiteSagaStorage(
        db_path=kwargs.get("db_path", ":memory:"),
    )


def _create_sqlite_outbox_storage(kwargs: dict):
    """Create SQLite outbox storage instance."""
    from sagaz.storage.backends.sqlite import SQLiteOutboxStorage

    return SQLiteOutboxStorage(
        db_path=kwargs.get("db_path", ":memory:"),
    )


# Storage registry mapping backend names to factory functions
_SAGA_STORAGE_REGISTRY = {
    "memory": lambda kwargs: InMemorySagaStorage(),
    "redis": _create_redis_saga_storage,
    "postgresql": _create_postgresql_saga_storage,
    "postgres": _create_postgresql_saga_storage,
    "pg": _create_postgresql_saga_storage,
    "sqlite": _create_sqlite_saga_storage,
}

_OUTBOX_STORAGE_REGISTRY = {
    "memory": _create_memory_outbox_storage,
    "redis": _create_redis_outbox_storage,
    "postgresql": _create_postgresql_outbox_storage,
    "postgres": _create_postgresql_outbox_storage,
    "pg": _create_postgresql_outbox_storage,
    "sqlite": _create_sqlite_outbox_storage,
}


def create_storage(
    backend: str = "memory",
    *,
    storage_type: StorageType = "saga",
    # Redis options
    redis_url: str = "redis://localhost:6379",
    key_prefix: str = "saga:",
    prefix: str = "sagaz:outbox",
    consumer_group: str = "sagaz-workers",
    default_ttl: int | None = None,
    # PostgreSQL options
    connection_string: str | None = None,
    pool_min_size: int = 5,
    pool_max_size: int = 20,
    # SQLite options
    db_path: str = ":memory:",
    # Additional kwargs
    **kwargs,
) -> SagaStorage | tuple:
    """
    Create a storage backend with a simple, unified API.

    This factory function makes it easy to switch between storage backends
    without changing your code structure. Supports both saga and outbox storage.

    Args:
        backend: Storage backend type - "memory", "redis", "postgresql", or "sqlite"
        storage_type: Type of storage - "saga", "outbox", or "both"
        redis_url: Redis connection URL (for redis backend)
        key_prefix: Key prefix for Redis saga storage
        prefix: Key prefix for Redis outbox storage
        consumer_group: Consumer group for Redis outbox storage
        default_ttl: TTL for completed sagas in seconds (for redis backend)
        connection_string: PostgreSQL connection string (for postgresql backend)
        pool_min_size: Minimum pool size (for postgresql backend)
        pool_max_size: Maximum pool size (for postgresql backend)
        db_path: Path to SQLite database file (for sqlite backend)
        **kwargs: Additional backend-specific options

    Returns:
        For storage_type="saga" or "outbox": A single storage instance
        For storage_type="both": A tuple of (saga_storage, outbox_storage)

    Raises:
        ValueError: If an unknown backend or storage_type is specified
        MissingDependencyError: If required packages aren't installed

    Examples:
        # In-memory saga storage (great for development/testing)
        >>> storage = create_storage("memory")

        # Redis saga storage (for distributed systems)
        >>> storage = create_storage(
        ...     "redis",
        ...     redis_url="redis://localhost:6379",
        ...     default_ttl=3600  # Expire completed sagas after 1 hour
        ... )

        # Redis outbox storage (NEW in v1.2.0)
        >>> outbox = create_storage(
        ...     "redis",
        ...     storage_type="outbox",
        ...     redis_url="redis://localhost:6379"
        ... )

        # Both saga and outbox from same backend
        >>> saga, outbox = create_storage(
        ...     "postgresql",
        ...     storage_type="both",
        ...     connection_string="postgresql://user:pass@localhost/mydb"
        ... )
    """
    backend = backend.lower().strip()

    # Validate backend
    if backend not in _SAGA_STORAGE_REGISTRY:
        available_backends = ["memory", "redis", "postgresql", "sqlite"]
        msg = (
            f"Unknown storage backend: '{backend}'\n"
            f"Available backends: {', '.join(available_backends)}"
        )
        raise ValueError(msg)

    # Validate storage_type
    if storage_type not in ("saga", "outbox", "both"):
        msg = f"Unknown storage_type: '{storage_type}'. Valid options: 'saga', 'outbox', 'both'"
        raise ValueError(msg)

    # Build kwargs dict for factory
    factory_kwargs = {
        "redis_url": redis_url,
        "key_prefix": key_prefix,
        "prefix": prefix,
        "consumer_group": consumer_group,
        "default_ttl": default_ttl,
        "connection_string": connection_string,
        "pool_min_size": pool_min_size,
        "pool_max_size": pool_max_size,
        "db_path": db_path,
        **kwargs,
    }

    try:
        if storage_type == "saga":
            return cast(SagaStorage, _SAGA_STORAGE_REGISTRY[backend](factory_kwargs))
        if storage_type == "outbox":
            return cast("tuple[Any, ...]", _OUTBOX_STORAGE_REGISTRY[backend](factory_kwargs))
        # both
        saga_storage = _SAGA_STORAGE_REGISTRY[backend](factory_kwargs)
        outbox_storage = _OUTBOX_STORAGE_REGISTRY[backend](factory_kwargs)
        return saga_storage, outbox_storage
    except MissingDependencyError:
        raise


def get_available_backends() -> dict[str, dict[str, Any]]:
    """
    Get information about available storage backends.

    Returns a dictionary with backend names as keys and their availability
    status and requirements as values.

    Returns:
        Dictionary of backend information

    Example:
        >>> backends = get_available_backends()
        >>> for name, info in backends.items():
        ...     status = "✓" if info["available"] else "✗"
        ...     print(f"{status} {name}: {info['description']}")
    """
    backends = {
        "memory": {
            "available": True,
            "description": "In-memory storage (no persistence)",
            "install": None,
            "best_for": "Development, testing, single-process applications",
            "supports": ["saga", "outbox"],
        }
    }

    # Check Redis availability
    try:
        import redis.asyncio

        backends["redis"] = {
            "available": True,
            "description": "Redis-based distributed storage",
            "install": None,
            "best_for": "Distributed systems, high throughput, auto-expiration",
            "supports": ["saga", "outbox"],
        }
    except ImportError:
        backends["redis"] = {
            "available": False,
            "description": "Redis-based distributed storage",
            "install": "pip install redis",
            "best_for": "Distributed systems, high throughput, auto-expiration",
            "supports": ["saga", "outbox"],
        }

    # Check PostgreSQL availability
    try:
        import asyncpg

        backends["postgresql"] = {
            "available": True,
            "description": "PostgreSQL ACID-compliant storage",
            "install": None,
            "best_for": "ACID compliance, complex queries, data integrity",
            "supports": ["saga", "outbox"],
        }
    except ImportError:
        backends["postgresql"] = {
            "available": False,
            "description": "PostgreSQL ACID-compliant storage",
            "install": "pip install asyncpg",
            "best_for": "ACID compliance, complex queries, data integrity",
            "supports": ["saga", "outbox"],
        }

    # Check SQLite availability
    try:
        import aiosqlite

        backends["sqlite"] = {
            "available": True,
            "description": "SQLite embedded storage",
            "install": None,
            "best_for": "Local development, testing, single-file persistence",
            "supports": ["saga", "outbox"],
        }
    except ImportError:
        backends["sqlite"] = {
            "available": False,
            "description": "SQLite embedded storage",
            "install": "pip install aiosqlite",
            "best_for": "Local development, testing, single-file persistence",
            "supports": ["saga", "outbox"],
        }

    return backends


def print_available_backends() -> None:
    """
    Print a formatted summary of available storage backends.

    Useful for checking which backends are available in the current environment.
    """
    backends = get_available_backends()

    print("\n=== Available Storage Backends ===\n")

    for name, info in backends.items():
        status = "✓" if info["available"] else "✗"
        supports = ", ".join(info.get("supports", ["saga"]))
        print(f"  {status} {name:<12} - {info['description']}")
        print(f"                   Supports: {supports}")

        if not info["available"] and info["install"]:
            print(f"                   Install: {info['install']}")

    print()
