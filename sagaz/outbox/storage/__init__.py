"""
Outbox Storage Implementations

Provides storage backends for the transactional outbox pattern.

Available backends:
    - InMemoryOutboxStorage: For testing
    - PostgreSQLOutboxStorage: Production (requires asyncpg)
"""

from sagaz.outbox.storage.base import OutboxStorage, OutboxStorageError
from sagaz.outbox.storage.memory import InMemoryOutboxStorage


# Lazy import for optional PostgreSQL backend
def PostgreSQLOutboxStorage(*args, **kwargs):
    """PostgreSQL outbox storage (requires asyncpg)."""
    from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage as _Impl
    return _Impl(*args, **kwargs)


__all__ = [
    "InMemoryOutboxStorage",
    "OutboxStorage",
    "OutboxStorageError",
    "PostgreSQLOutboxStorage",
]
