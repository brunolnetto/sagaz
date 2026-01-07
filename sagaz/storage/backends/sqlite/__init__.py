"""
SQLite Storage Backends.

Provides lightweight embedded storage using SQLite.

Usage:
    >>> from sagaz.storage.backends.sqlite import SQLiteSagaStorage, SQLiteOutboxStorage
    >>>
    >>> # Saga storage
    >>> saga_storage = SQLiteSagaStorage("./sagas.db")
    >>>
    >>> # Outbox storage
    >>> outbox_storage = SQLiteOutboxStorage("./outbox.db")
"""

from .saga import SQLiteSagaStorage, AIOSQLITE_AVAILABLE
from .outbox import SQLiteOutboxStorage

__all__ = [
    "SQLiteSagaStorage",
    "SQLiteOutboxStorage",
    "AIOSQLITE_AVAILABLE",
]
