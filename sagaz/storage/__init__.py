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
from .core import (
    # Errors
    CapacityError,
    ConcurrencyError,
    ConnectionError,
    NotFoundError,
    SerializationError,
    StorageError,
    TransactionError,
    TransferError,
    # Health
    HealthCheckResult,
    HealthCheckable,
    HealthStatus,
    StorageStatistics,
    # Connection
    ConnectionConfig,
    ConnectionManager,
    PoolStatus,
    # Base
    BaseStorage,
    TransferableStorage,
    # Serialization
    deserialize,
    serialize,
)

# Interfaces
from .interfaces import (
    OutboxStorage,
    OutboxStorageError,
    SagaStepState,
    SagaStorage,
    Transferable,
)

# Factory
from .factory import create_storage, get_available_backends, print_available_backends

# =============================================================================
# StorageManager - Unified Facade
# =============================================================================
from .manager import (
    BaseStorageManager,
    StorageManager,
    create_storage_manager,
)

# Implementations
from .backends.memory import InMemorySagaStorage
from .backends.postgresql import PostgreSQLSagaStorage
from .backends.redis import RedisSagaStorage

__all__ = [
    # =========================================================================
    # StorageManager - Unified Facade
    # =========================================================================
    "BaseStorageManager",
    "StorageManager",
    "create_storage_manager",
    
    # =========================================================================
    # Storage Implementations
    # =========================================================================
    "InMemorySagaStorage",
    "PostgreSQLSagaStorage",
    "RedisSagaStorage",
    
    # =========================================================================
    # Factory Functions
    # =========================================================================
    "create_storage",
    "get_available_backends",
    "print_available_backends",
    
    # =========================================================================
    # Interfaces
    # =========================================================================
    "SagaStorage",
    "OutboxStorage",
    "SagaStepState",
    "Transferable",
    
    # =========================================================================
    # Core Infrastructure
    # =========================================================================
    # Errors
    "StorageError",
    "ConnectionError",
    "NotFoundError",
    "SerializationError",
    "TransferError",
    "TransactionError",
    "ConcurrencyError",
    "CapacityError",
    "OutboxStorageError",
    # Health
    "HealthStatus",
    "HealthCheckResult",
    "StorageStatistics",
    "HealthCheckable",
    # Connection
    "ConnectionConfig",
    "ConnectionManager",
    "PoolStatus",
    # Base
    "BaseStorage",
    "TransferableStorage",
    # Serialization
    "serialize",
    "deserialize",
]
