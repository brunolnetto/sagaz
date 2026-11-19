"""Exporter reads of the SQLite saga log (ADR-013, #480).

SQLite has one writer at a time, so ``saga_log_event``'s rowid grows in commit
order (the log is append-only, so it is never reused): it is the position.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sagaz.core.storage.saga_log import _codec as codec
from sagaz.core.storage.saga_log._model import ExportBatch, ExportedEvent

_READ = (
    "SELECT e.rowid AS position, e.*, t.coordination, t.flow FROM saga_log_event e"
    " LEFT JOIN saga_transaction t"
    " ON t.tenant_id = e.tenant_id AND t.transaction_id = e.transaction_id"
    " WHERE e.rowid > ? ORDER BY e.rowid LIMIT ?"
)


class SQLiteExportMixin:
    # Provided by the store. Reads take the write lock: on the shared
    # connection, a read between a write's statements would see rows that
    # are not committed yet, and may never be.
    _lock: asyncio.Lock
    _connection: Callable[[], Awaitable[Any]]

    async def read_committed(self, after: str | None = None, limit: int = 500) -> ExportBatch:
        conn = await self._connection()
        async with self._lock:
            cursor = await conn.execute(_READ, (0 if after is None else int(after), limit))
            rows = list(await cursor.fetchall())
        events = [
            ExportedEvent(codec.to_event(row), row["coordination"], row["flow"]) for row in rows
        ]
        return ExportBatch(events, str(rows[-1]["position"]) if rows else after)

    async def load_cursor(self, name: str) -> str | None:
        conn = await self._connection()
        cursor = await conn.execute(
            "SELECT position FROM saga_export_cursor WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        return None if row is None else str(row[0])

    async def save_cursor(self, name: str, position: str) -> None:
        conn = await self._connection()
        async with self._lock:
            await self._upsert_cursor(conn, name, position)

    @staticmethod
    async def _upsert_cursor(conn: Any, name: str, position: str) -> None:
        await conn.execute(
            "INSERT INTO saga_export_cursor (name, position, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (name) DO UPDATE SET position = excluded.position,"
            " updated_at = excluded.updated_at",
            (name, position, datetime.now(UTC).isoformat()),
        )
        await conn.commit()
