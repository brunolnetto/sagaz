"""
Saga storage abstractions and implementations

Provides pluggable storage backends for saga state persistence.

Quick Start:
    >>> from sagaz.storage import create_storage

    # In-memory (for development/testing)
    >>> storage = create_storage("memory")

    # Redis (for distributed systems)
    >>> storage = create_storage("redis", redis_url="redis://localhost:6379")

    # PostgreSQL (for ACID compliance)
    >>> storage = create_storage("postgresql", connection_string="postgresql://...")
"""

from .base import (
    SagaNotFoundError,
    SagaStepState,
    SagaStorage,
    SagaStorageConnectionError,
    SagaStorageError,
)
from .factory import create_storage, get_available_backends, print_available_backends
from .memory import InMemorySagaStorage
from .postgresql import PostgreSQLSagaStorage
from .redis import RedisSagaStorage

__all__ = [
    # Storage implementations (for direct use)
    "InMemorySagaStorage",
    "PostgreSQLSagaStorage",
    "RedisSagaStorage",
    "SagaNotFoundError",
    "SagaStepState",
    # Base classes and exceptions
    "SagaStorage",
    "SagaStorageConnectionError",
    "SagaStorageError",
    # Factory functions (recommended API)
    "create_storage",
    "get_available_backends",
    "print_available_backends",
]
