"""
Sagaz Storage Core Module.

Provides shared infrastructure for all storage backends:
- Error hierarchy
- Serialization utilities
- Health check infrastructure
- Connection management
- Base storage classes

Usage:
    from sagaz.storage.core import (
        # Errors
        StorageError,
        ConnectionError,
        NotFoundError,
        SerializationError,
        TransferError,
        
        # Health
        HealthStatus,
        HealthCheckResult,
        StorageStatistics,
        
        # Connection
        ConnectionConfig,
        ConnectionManager,
        PoolStatus,
        
        # Base
        BaseStorage,
        TransferableStorage,
        
        # Serialization
        serialize,
        deserialize,
    )
"""

from .base import BaseStorage, TransferableStorage
from .connection import (
    ConnectionConfig,
    ConnectionManager,
    PoolStatus,
    SingleConnectionManager,
)
from .errors import (
    CapacityError,
    ConcurrencyError,
    ConnectionError,
    NotFoundError,
    SerializationError,
    StorageError,
    TransactionError,
    TransferError,
)
from .health import (
    HealthCheckable,
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
    check_health_with_timeout,
)
from .serialization import (
    StorageEncoder,
    deserialize,
    deserialize_from_redis,
    serialize,
    serialize_for_redis,
    storage_decoder,
)

__all__ = [
    # Errors
    "StorageError",
    "ConnectionError",
    "NotFoundError",
    "SerializationError",
    "TransferError",
    "TransactionError",
    "ConcurrencyError",
    "CapacityError",
    # Health
    "HealthStatus",
    "HealthCheckResult",
    "StorageStatistics",
    "HealthCheckable",
    "check_health_with_timeout",
    # Connection
    "ConnectionConfig",
    "ConnectionManager",
    "SingleConnectionManager",
    "PoolStatus",
    # Base
    "BaseStorage",
    "TransferableStorage",
    # Serialization
    "serialize",
    "deserialize",
    "serialize_for_redis",
    "deserialize_from_redis",
    "StorageEncoder",
    "storage_decoder",
]
