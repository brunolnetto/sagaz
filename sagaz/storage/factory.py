"""
Storage Factory - Simplified API for creating saga storage backends

This module provides a user-friendly factory function for creating storage
backends without needing to import specific storage classes directly.
"""

from typing import Any

from sagaz.exceptions import MissingDependencyError
from sagaz.storage.base import SagaStorage
from sagaz.storage.memory import InMemorySagaStorage


def _create_redis_storage(kwargs: dict) -> SagaStorage:
    """Create Redis storage instance."""
    from sagaz.storage.redis import RedisSagaStorage

    return RedisSagaStorage(
        redis_url=kwargs.get("redis_url", "redis://localhost:6379"),
        key_prefix=kwargs.get("key_prefix", "saga:"),
        default_ttl=kwargs.get("default_ttl"),
    )


def _create_postgresql_storage(kwargs: dict) -> SagaStorage:
    """Create PostgreSQL storage instance."""
    connection_string = kwargs.get("connection_string")
    if not connection_string:
        msg = (
            "PostgreSQL backend requires a connection_string.\n"
            "Example: create_storage('postgresql', connection_string='postgresql://user:pass@localhost/db')"
        )
        raise ValueError(
            msg
        )
    from sagaz.storage.postgresql import PostgreSQLSagaStorage

    return PostgreSQLSagaStorage(
        connection_string=connection_string,
        pool_min_size=kwargs.get("pool_min_size", 5),
        pool_max_size=kwargs.get("pool_max_size", 20),
    )


# Storage registry mapping backend names to factory functions
_STORAGE_REGISTRY = {
    "memory": lambda kwargs: InMemorySagaStorage(),
    "redis": _create_redis_storage,
    "postgresql": _create_postgresql_storage,
    "postgres": _create_postgresql_storage,
    "pg": _create_postgresql_storage,
}


def create_storage(
    backend: str = "memory",
    *,
    # Redis options
    redis_url: str = "redis://localhost:6379",
    key_prefix: str = "saga:",
    default_ttl: int | None = None,
    # PostgreSQL options
    connection_string: str | None = None,
    pool_min_size: int = 5,
    pool_max_size: int = 20,
    # Additional kwargs
    **kwargs,
) -> SagaStorage:
    """
    Create a saga storage backend with a simple, unified API.

    This factory function makes it easy to switch between storage backends
    without changing your code structure.

    Args:
        backend: Storage backend type - "memory", "redis", or "postgresql"
        redis_url: Redis connection URL (for redis backend)
        key_prefix: Key prefix for Redis (for redis backend)
        default_ttl: TTL for completed sagas in seconds (for redis backend)
        connection_string: PostgreSQL connection string (for postgresql backend)
        pool_min_size: Minimum pool size (for postgresql backend)
        pool_max_size: Maximum pool size (for postgresql backend)
        **kwargs: Additional backend-specific options

    Returns:
        Configured SagaStorage instance

    Raises:
        ValueError: If an unknown backend is specified
        MissingDependencyError: If required packages aren't installed

    Examples:
        # In-memory storage (great for development/testing)
        >>> storage = create_storage("memory")

        # Redis storage (for distributed systems)
        >>> storage = create_storage(
        ...     "redis",
        ...     redis_url="redis://localhost:6379",
        ...     default_ttl=3600  # Expire completed sagas after 1 hour
        ... )

        # PostgreSQL storage (for ACID compliance)
        >>> storage = create_storage(
        ...     "postgresql",
        ...     connection_string="postgresql://user:pass@localhost/mydb"
        ... )
    """
    backend = backend.lower().strip()

    if backend not in _STORAGE_REGISTRY:
        available_backends = ["memory", "redis", "postgresql"]
        msg = (
            f"Unknown storage backend: '{backend}'\n"
            f"Available backends: {', '.join(available_backends)}"
        )
        raise ValueError(
            msg
        )

    # Build kwargs dict for factory
    factory_kwargs = {
        "redis_url": redis_url,
        "key_prefix": key_prefix,
        "default_ttl": default_ttl,
        "connection_string": connection_string,
        "pool_min_size": pool_min_size,
        "pool_max_size": pool_max_size,
        **kwargs,
    }

    try:
        return _STORAGE_REGISTRY[backend](factory_kwargs)
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
        }
    except ImportError:  # pragma: no cover
        backends["redis"] = {
            "available": False,
            "description": "Redis-based distributed storage",
            "install": "pip install redis",
            "best_for": "Distributed systems, high throughput, auto-expiration",
        }

    # Check PostgreSQL availability
    try:
        import asyncpg

        backends["postgresql"] = {
            "available": True,
            "description": "PostgreSQL ACID-compliant storage",
            "install": None,
            "best_for": "ACID compliance, complex queries, data integrity",
        }
    except ImportError:  # pragma: no cover
        backends["postgresql"] = {
            "available": False,
            "description": "PostgreSQL ACID-compliant storage",
            "install": "pip install asyncpg",
            "best_for": "ACID compliance, complex queries, data integrity",
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
        print(f"  {status} {name:<12} - {info['description']}")

        if not info["available"] and info["install"]:
            print(f"                   Install: {info['install']}")

    print()
