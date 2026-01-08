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

from .outbox import SQLiteOutboxStorage
from .saga import AIOSQLITE_AVAILABLE, SQLiteSagaStorage

__all__ = [
    "AIOSQLITE_AVAILABLE",
    "SQLiteOutboxStorage",
    "SQLiteSagaStorage",
]
