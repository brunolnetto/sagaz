"""SQLite event store, for development, tests and single-node deployments."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from sagaz.core.events import SagaEvent
from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot

try:
    import aiosqlite
except ImportError:  # pragma: no cover - aiosqlite is a dev dependency
    aiosqlite = None  # type: ignore[assignment]

SCHEMA = """
CREATE TABLE IF NOT EXISTS saga_events (
    tenant_id   TEXT    NOT NULL DEFAULT 'default',
    saga_id     TEXT    NOT NULL,
    sequence    INTEGER NOT NULL,
    event_id    TEXT    NOT NULL UNIQUE,
    event_type  TEXT    NOT NULL,
    occurred_at TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, saga_id, sequence)
);
CREATE TABLE IF NOT EXISTS saga_event_snapshots (
    tenant_id  TEXT    NOT NULL DEFAULT 'default',
    saga_id    TEXT    NOT NULL,
    sequence   INTEGER NOT NULL,
    state      TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, saga_id, sequence)
);
"""


def _tenant_clause() -> tuple[str, tuple[str, ...]]:
    tenant = scoped_tenant()
    return ("", ()) if tenant is None else (" AND tenant_id = ?", (tenant,))


class SQLiteEventStore(SagaEventStore):
    """Event store in a SQLite file (or ``":memory:"``)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        if aiosqlite is None:  # pragma: no cover
            msg = "aiosqlite"
            raise MissingDependencyError(msg, "SQLite event store")
        self.db_path = db_path
        self._conn: Any = None
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def _connection(self) -> Any:
        # Initialized once, and published only when ready: a concurrent caller
        # must neither open a second connection nor use a half-made schema.
        if self._conn is None:
            async with self._init_lock:
                if self._conn is None:
                    conn = await aiosqlite.connect(self.db_path)
                    await conn.executescript(SCHEMA)
                    await conn.commit()
                    self._conn = conn
        return self._conn

    async def append(self, event: SagaEvent) -> SagaEvent:
        tenant = write_tenant(event.tenant_id)
        conn = await self._connection()
        async with self._lock:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM saga_events"
                " WHERE tenant_id = ? AND saga_id = ?",
                (tenant, event.saga_id),
            )
            (last,) = await cursor.fetchone()
            stored = replace(event, sequence=last + 1, tenant_id=tenant)
            await conn.execute(
                "INSERT INTO saga_events"
                " (tenant_id, saga_id, sequence, event_id, event_type, occurred_at, body)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant,
                    stored.saga_id,
                    stored.sequence,
                    stored.event_id,
                    stored.event_type,
                    stored.occurred_at.isoformat(),
                    json.dumps(stored.to_dict()),
                ),
            )
            await conn.commit()
        return stored

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        return await self.load_stream_after(saga_id, 0)

    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        conn = await self._connection()
        clause, args = _tenant_clause()
        cursor = await conn.execute(
            "SELECT body FROM saga_events WHERE saga_id = ? AND sequence > ?"  # nosec B608 - only constant SQL fragments are interpolated; values are bound parameters
            f"{clause} ORDER BY tenant_id, sequence",
            (saga_id, after_sequence, *args),
        )
        return [SagaEvent.from_dict(json.loads(body)) for (body,) in await cursor.fetchall()]

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        tenant = write_tenant(snapshot.tenant_id)
        conn = await self._connection()
        async with self._lock:
            await conn.execute(
                "INSERT OR REPLACE INTO saga_event_snapshots"
                " (tenant_id, saga_id, sequence, state, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    tenant,
                    snapshot.saga_id,
                    snapshot.sequence,
                    json.dumps(snapshot.state),
                    snapshot.created_at.isoformat(),
                ),
            )
            await conn.commit()

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        conn = await self._connection()
        clause, args = _tenant_clause()
        cursor = await conn.execute(
            "SELECT tenant_id, sequence, state, created_at FROM saga_event_snapshots"  # nosec B608 - only constant SQL fragments are interpolated; values are bound parameters
            f" WHERE saga_id = ?{clause} ORDER BY sequence DESC LIMIT 1",
            (saga_id, *args),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        tenant, sequence, state, created_at = row
        return SagaSnapshot(
            saga_id, sequence, json.loads(state), tenant, datetime.fromisoformat(created_at)
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
