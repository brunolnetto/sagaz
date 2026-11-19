"""Exporter reads of the PostgreSQL saga log (ADR-013, #480).

A sequence is not commit-ordered: a transaction that commits later can hold a
lower value, and a poller that already moved past it would skip it. Each event
records its writing transaction (``writer_xid``), and the exporter reads only
rows written by transactions older than every transaction still running
(``pg_snapshot_xmin``): those are all finished, so nothing can be committed
before the position later. A long-running transaction delays the export; it
never loses events.

The position is ``writer_xid``, then the event's key, as a JSON array.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sagaz.core.storage.backends.postgresql._tenancy import acquire_scoped
from sagaz.core.storage.saga_log import _codec as codec
from sagaz.core.storage.saga_log._model import ExportBatch, ExportedEvent

_SELECT = (
    "SELECT e.*, e.writer_xid::text AS xid, t.coordination, t.flow FROM saga_log_event e"
    " LEFT JOIN saga_transaction t"
    " ON t.tenant_id = e.tenant_id AND t.transaction_id = e.transaction_id"
    " WHERE e.writer_xid < pg_snapshot_xmin(pg_current_snapshot())"
)
_ORDER = " ORDER BY e.writer_xid, e.tenant_id, e.transaction_id, e.sequence LIMIT $1"
_FIRST = _SELECT + _ORDER
_AFTER = (
    _SELECT + " AND (e.writer_xid, e.tenant_id, e.transaction_id, e.sequence)"
    " > ($2::text::xid8, $3, $4, $5)" + _ORDER
)


def _position(row: Any) -> str:
    return json.dumps([row["xid"], row["tenant_id"], row["transaction_id"], row["sequence"]])


class PostgreSQLExportMixin:
    _get_pool: Callable[[], Awaitable[Any]]  # provided by the store

    async def read_committed(self, after: str | None = None, limit: int = 500) -> ExportBatch:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            if after is None:
                rows = await conn.fetch(_FIRST, limit)
            else:
                xid, tenant, transaction_id, sequence = json.loads(after)
                rows = await conn.fetch(_AFTER, limit, xid, tenant, transaction_id, sequence)
        events = [
            ExportedEvent(codec.to_event(row), row["coordination"], row["flow"]) for row in rows
        ]
        return ExportBatch(events, _position(rows[-1]) if rows else after)

    async def load_cursor(self, name: str) -> str | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            position = await conn.fetchval(
                "SELECT position FROM saga_export_cursor WHERE name = $1", name
            )
        return None if position is None else str(position)

    async def save_cursor(self, name: str, position: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO saga_export_cursor (name, position, updated_at) VALUES ($1, $2, $3)"
                " ON CONFLICT (name) DO UPDATE SET position = EXCLUDED.position,"
                " updated_at = EXCLUDED.updated_at",
                name,
                position,
                datetime.now(UTC),
            )
