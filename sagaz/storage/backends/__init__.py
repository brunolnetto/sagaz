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


_BACKEND_IMPORTS = {
    "InMemorySagaStorage": ("memory", "InMemorySagaStorage"),
    "InMemoryOutboxStorage": ("memory", "InMemoryOutboxStorage"),
    "InMemorySnapshotStorage": ("memory_snapshot", "InMemorySnapshotStorage"),
    "RedisSagaStorage": ("redis", "RedisSagaStorage"),
    "RedisOutboxStorage": ("redis", "RedisOutboxStorage"),
    "RedisSnapshotStorage": ("redis", "RedisSnapshotStorage"),
    "PostgreSQLSagaStorage": ("postgresql", "PostgreSQLSagaStorage"),
    "PostgreSQLOutboxStorage": ("postgresql", "PostgreSQLOutboxStorage"),
    "PostgreSQLSnapshotStorage": ("postgresql", "PostgreSQLSnapshotStorage"),
    "SQLiteSagaStorage": ("sqlite", "SQLiteSagaStorage"),
    "SQLiteOutboxStorage": ("sqlite", "SQLiteOutboxStorage"),
    "S3SnapshotStorage": ("s3", "S3SnapshotStorage"),
}


def __getattr__(name: str):
    """Lazy import of storage backends."""
    if name in _BACKEND_IMPORTS:
        module_name, class_name = _BACKEND_IMPORTS[name]
        module = __import__(f"sagaz.storage.backends.{module_name}", fromlist=[class_name])
        return getattr(module, class_name)

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
