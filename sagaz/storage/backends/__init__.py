"""
Sagaz Storage Backends.

Provides storage implementations for different backends.

Available backends:
- memory: In-memory storage for testing
- redis: Redis-based storage for distributed systems
- postgresql: PostgreSQL storage for ACID compliance
- sqlite: SQLite embedded storage for local development
"""

# These are imported lazily to avoid import errors when dependencies are missing

__all__ = [
    # Memory
    "InMemorySagaStorage",
    "InMemoryOutboxStorage",
    # Redis
    "RedisSagaStorage",
    "RedisOutboxStorage",
    # PostgreSQL
    "PostgreSQLSagaStorage",
    "PostgreSQLOutboxStorage",
    # SQLite
    "SQLiteSagaStorage",
    "SQLiteOutboxStorage",
]



def __getattr__(name: str):
    """Lazy import of storage backends."""
    if name == "InMemorySagaStorage":
        from .memory import InMemorySagaStorage
        return InMemorySagaStorage
    
    if name == "InMemoryOutboxStorage":
        from .memory import InMemoryOutboxStorage
        return InMemoryOutboxStorage
    
    if name == "RedisSagaStorage":
        from .redis import RedisSagaStorage
        return RedisSagaStorage
    
    if name == "RedisOutboxStorage":
        from .redis import RedisOutboxStorage
        return RedisOutboxStorage
    
    if name == "PostgreSQLSagaStorage":
        from .postgresql import PostgreSQLSagaStorage
        return PostgreSQLSagaStorage
    
    if name == "PostgreSQLOutboxStorage":
        from .postgresql import PostgreSQLOutboxStorage
        return PostgreSQLOutboxStorage
    
    if name == "SQLiteSagaStorage":
        from .sqlite import SQLiteSagaStorage
        return SQLiteSagaStorage
    
    if name == "SQLiteOutboxStorage":
        from .sqlite import SQLiteOutboxStorage
        return SQLiteOutboxStorage
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

