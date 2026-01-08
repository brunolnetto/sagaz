"""
Saga storage abstractions and implementations.

Provides pluggable storage backends for saga state persistence.

Quick Start:
    >>> from sagaz.storage import create_storage

    # In-memory (for development/testing)
    >>> storage = create_storage("memory")

    # Redis (for distributed systems)
    >>> storage = create_storage("redis", redis_url="redis://localhost:6379")

    # PostgreSQL (for ACID compliance)
    >>> storage = create_storage("postgresql", connection_string="postgresql://...")

New in v1.4.0 - StorageManager (Recommended):
    >>> from sagaz.storage import create_storage_manager
    >>>
    >>> # Same backend for saga and outbox (shared connection pool)
    >>> async with create_storage_manager("postgresql://...") as manager:
    ...     await manager.saga.save_saga_state(...)
    ...     await manager.outbox.insert(event)
    >>>
    >>> # Different backends for saga and outbox (hybrid mode)
    >>> manager = create_storage_manager(
    ...     saga_url="postgresql://localhost/saga_db",
    ...     outbox_url="redis://localhost:6379",
    ... )
    >>> await manager.initialize()
    >>> # saga uses PostgreSQL, outbox uses Redis

Core Infrastructure (v1.2.0+):
    >>> from sagaz.storage.core import StorageError, HealthStatus, serialize
    >>> from sagaz.storage.interfaces import SagaStorage, OutboxStorage, Transferable
"""



# Core infrastructure (new in v1.2.0)
# Implementations
from .backends.memory import InMemorySagaStorage
from .backends.postgresql import PostgreSQLSagaStorage
from .backends.redis import RedisSagaStorage
from .core import (
    # Base
    BaseStorage,
    # Errors
    CapacityError,
    ConcurrencyError,
    # Connection
    ConnectionConfig,
    ConnectionError,
    ConnectionManager,
    HealthCheckable,
    # Health
    HealthCheckResult,
    HealthStatus,
    NotFoundError,
    PoolStatus,
    SerializationError,
    StorageError,
    StorageStatistics,
    TransactionError,
    TransferableStorage,
    TransferError,
    # Serialization
    deserialize,
    serialize,
)

# Factory
from .factory import create_storage, get_available_backends, print_available_backends

# Interfaces
from .interfaces import (
    OutboxStorage,
    OutboxStorageError,
    SagaStepState,
    SagaStorage,
    Transferable,
)

# =============================================================================
# StorageManager - Unified Facade
# =============================================================================
from .manager import (
    BaseStorageManager,
    StorageManager,
    create_storage_manager,
)

__all__ = [
    # Base
    "BaseStorage",
    # =========================================================================
    # StorageManager - Unified Facade
    # =========================================================================
    "BaseStorageManager",
    "CapacityError",
    "ConcurrencyError",
    # Connection
    "ConnectionConfig",
    "ConnectionError",
    "ConnectionManager",
    "HealthCheckResult",
    "HealthCheckable",
    # Health
    "HealthStatus",
    # =========================================================================
    # Storage Implementations
    # =========================================================================
    "InMemorySagaStorage",
    "NotFoundError",
    "OutboxStorage",
    "OutboxStorageError",
    "PoolStatus",
    "PostgreSQLSagaStorage",
    "RedisSagaStorage",
    "SagaStepState",
    # =========================================================================
    # Interfaces
    # =========================================================================
    "SagaStorage",
    "SerializationError",
    # =========================================================================
    # Core Infrastructure
    # =========================================================================
    # Errors
    "StorageError",
    "StorageManager",
    "StorageStatistics",
    "TransactionError",
    "TransferError",
    "Transferable",
    "TransferableStorage",
    # =========================================================================
    # Factory Functions
    # =========================================================================
    "create_storage",
    "create_storage_manager",
    "deserialize",
    "get_available_backends",
    "print_available_backends",
    # Serialization
    "serialize",
]
