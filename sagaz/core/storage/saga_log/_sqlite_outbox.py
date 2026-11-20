"""The SQLite saga log's outbox, on the log's own connection (#500).

SQLite takes one writer at a time. A relay with its own connection to the
log's file competes with the log's writes for the lock: under load, one side
waits out the busy timeout and fails with "database is locked". This outbox
storage uses the log store's connection, and runs each operation under the
store's write lock, so the relay and the log take turns instead of colliding.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

_OWN_LIFECYCLE = frozenset({"initialize", "close"})
# Set while this task holds the store's lock: outbox methods call one another
# (update_status reads get_by_id), and the store's asyncio.Lock is not reentrant.
_HOLDING: ContextVar[bool] = ContextVar("sagaz_sqlite_outbox_holding", default=False)


class SharedSQLiteOutboxStorage(SQLiteOutboxStorage):
    """``SQLiteOutboxStorage`` on a ``SQLiteSagaLogStore``'s connection and lock."""

    def __init__(self, store: Any) -> None:
        super().__init__(store.db_path)
        self._store = store

    async def _get_connection(self) -> Any:
        self._initialized = True  # the store creates the outbox table on connect
        return await self._store._connection()

    async def close(self) -> None:
        """The connection belongs to the store, which closes it."""


def _locked(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(method)
    async def wrapper(self: SharedSQLiteOutboxStorage, *args: Any, **kwargs: Any) -> Any:
        if _HOLDING.get():  # a nested call: the lock is already ours
            return await method(self, *args, **kwargs)
        await self._store._connection()  # connect outside the lock (it takes its own)
        async with self._store._lock:
            token = _HOLDING.set(True)
            try:
                return await method(self, *args, **kwargs)
            finally:
                _HOLDING.reset(token)

    return wrapper


for _name, _method in inspect.getmembers(SQLiteOutboxStorage, inspect.iscoroutinefunction):
    if not _name.startswith("_") and _name not in _OWN_LIFECYCLE:
        setattr(SharedSQLiteOutboxStorage, _name, _locked(_method))
