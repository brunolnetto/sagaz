"""
Sagaz Storage Backends.

Provides storage implementations for different backends.

Available backends:
- memory: In-memory storage for testing
- redis: Redis-based storage for distributed systems
- postgresql: PostgreSQL storage for ACID compliance
- sqlite: SQLite embedded storage for local development
- s3: AWS S3 storage for scalable object storage
"""

# These are imported lazily to avoid import errors when dependencies are missing

__all__ = [
    "InMemoryOutboxStorage",
    # Memory
    "InMemorySagaStorage",
    "InMemorySnapshotStorage",
    "PostgreSQLOutboxStorage",
    # PostgreSQL
    "PostgreSQLSagaStorage",
    "PostgreSQLSnapshotStorage",
    "RedisOutboxStorage",
    # Redis
    "RedisSagaStorage",
    "RedisSnapshotStorage",
    # S3
    "S3SnapshotStorage",
    "SQLiteOutboxStorage",
    # SQLite
    "SQLiteSagaStorage",
]


def __getattr__(name: str):
    """Lazy import of storage backends."""
    if name == "InMemorySagaStorage":
        from .memory import InMemorySagaStorage

        return InMemorySagaStorage

    if name == "InMemoryOutboxStorage":
        from .memory import InMemoryOutboxStorage

        return InMemoryOutboxStorage

    if name == "InMemorySnapshotStorage":
        from .memory_snapshot import InMemorySnapshotStorage

        return InMemorySnapshotStorage

    if name == "RedisSagaStorage":
        from .redis import RedisSagaStorage

        return RedisSagaStorage

    if name == "RedisOutboxStorage":
        from .redis import RedisOutboxStorage

        return RedisOutboxStorage

    if name == "RedisSnapshotStorage":
        from .redis import RedisSnapshotStorage

        return RedisSnapshotStorage

    if name == "PostgreSQLSagaStorage":
        from .postgresql import PostgreSQLSagaStorage

        return PostgreSQLSagaStorage

    if name == "PostgreSQLOutboxStorage":
        from .postgresql import PostgreSQLOutboxStorage

        return PostgreSQLOutboxStorage

    if name == "PostgreSQLSnapshotStorage":
        from .postgresql import PostgreSQLSnapshotStorage

        return PostgreSQLSnapshotStorage

    if name == "SQLiteSagaStorage":
        from .sqlite import SQLiteSagaStorage

        return SQLiteSagaStorage

    if name == "SQLiteOutboxStorage":
        from .sqlite import SQLiteOutboxStorage

        return SQLiteOutboxStorage

    if name == "S3SnapshotStorage":
        from .s3 import S3SnapshotStorage

        return S3SnapshotStorage

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
