"""SQLite participant state, for single-node deployments and tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.choreography.events import Event
from sagaz.choreography.state._base import COMPENSATED, COMPLETED, ParticipantState
from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import write_tenant

try:
    import aiosqlite
except ImportError:  # pragma: no cover - aiosqlite is a dev dependency
    aiosqlite = None  # type: ignore[assignment]

SCHEMA = """
CREATE TABLE IF NOT EXISTS choreography_actions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      TEXT NOT NULL,
    participant    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    event_id       TEXT NOT NULL,
    body           TEXT NOT NULL,
    UNIQUE (tenant_id, participant, event_id)
);
CREATE INDEX IF NOT EXISTS idx_choreography_actions_tx
    ON choreography_actions (tenant_id, participant, correlation_id);
CREATE TABLE IF NOT EXISTS choreography_transactions (
    tenant_id      TEXT NOT NULL,
    participant    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    state          TEXT NOT NULL,
    ended_at       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, participant, correlation_id)
);
CREATE TABLE IF NOT EXISTS choreography_deliveries (
    tenant_id   TEXT NOT NULL,
    participant TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    handled_at  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, participant, event_id)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteParticipantState(ParticipantState):
    """Participant state in a SQLite file (or ``":memory:"``)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        if aiosqlite is None:  # pragma: no cover
            msg = "aiosqlite"
            raise MissingDependencyError(msg, "SQLite participant state")
        self.db_path = db_path
        self._conn: Any = None
        self._lock = asyncio.Lock()

    async def _connection(self) -> Any:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.executescript(SCHEMA)
            await self._conn.commit()
        return self._conn

    async def record_action(self, participant: str, event: Event) -> None:
        if not event.saga_id:
            return
        conn = await self._connection()
        tenant = write_tenant()
        async with self._lock:
            await conn.execute(
                "INSERT OR IGNORE INTO choreography_actions"
                " (tenant_id, participant, correlation_id, event_id, body)"
                " SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM choreography_transactions"
                "  WHERE tenant_id = ? AND participant = ? AND correlation_id = ?)",
                (
                    tenant,
                    participant,
                    event.saga_id,
                    event.event_id,
                    json.dumps(event.to_dict()),
                    tenant,
                    participant,
                    event.saga_id,
                ),
            )
            await conn.commit()

    async def finish(
        self, participant: str, correlation_id: str, *, compensated: bool
    ) -> list[Event]:
        conn = await self._connection()
        key = (write_tenant(), participant, correlation_id)
        async with self._lock:
            cursor = await conn.execute(
                "SELECT body FROM choreography_actions"
                " WHERE tenant_id = ? AND participant = ? AND correlation_id = ? ORDER BY id",
                key,
            )
            done = [Event.from_dict(json.loads(body)) for (body,) in await cursor.fetchall()]
            await conn.execute(
                "DELETE FROM choreography_actions"
                " WHERE tenant_id = ? AND participant = ? AND correlation_id = ?",
                key,
            )
            await conn.execute(
                "INSERT INTO choreography_transactions"
                " (tenant_id, participant, correlation_id, state, ended_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (tenant_id, participant, correlation_id) DO UPDATE SET"
                " state = CASE WHEN excluded.state = 'compensated' THEN 'compensated'"
                " ELSE choreography_transactions.state END",
                (*key, COMPENSATED if compensated else COMPLETED, _now()),
            )
            await conn.commit()
        return done

    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        conn = await self._connection()
        cursor = await conn.execute(
            "SELECT 1 FROM choreography_transactions WHERE tenant_id = ? AND participant = ?"
            " AND correlation_id = ? AND state = 'compensated'",
            (write_tenant(), participant, correlation_id),
        )
        return await cursor.fetchone() is not None

    async def first_delivery(self, participant: str, event_id: str) -> bool:
        conn = await self._connection()
        async with self._lock:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO choreography_deliveries"
                " (tenant_id, participant, event_id, handled_at) VALUES (?, ?, ?, ?)",
                (write_tenant(), participant, event_id, _now()),
            )
            await conn.commit()
        return bool(cursor.rowcount == 1)

    async def prune(self, older_than: timedelta) -> int:
        conn = await self._connection()
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        async with self._lock:
            ended = await conn.execute(
                "DELETE FROM choreography_transactions WHERE ended_at < ?", (cutoff,)
            )
            seen = await conn.execute(
                "DELETE FROM choreography_deliveries WHERE handled_at < ?", (cutoff,)
            )
            await conn.commit()
        return int(ended.rowcount) + int(seen.rowcount)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
