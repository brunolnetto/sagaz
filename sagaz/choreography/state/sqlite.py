"""SQLite participant state, for single-node deployments and tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.choreography.events import Event
from sagaz.choreography.state._base import COMPENSATED, COMPLETED, Deadline, ParticipantState
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
CREATE TABLE IF NOT EXISTS choreography_deadlines (
    tenant_id      TEXT NOT NULL,
    participant    TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    due_at         TEXT NOT NULL,
    claimed_until  TEXT,
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
            for table in ("choreography_actions", "choreography_deadlines"):
                await conn.execute(
                    f"DELETE FROM {table}"
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

    async def set_deadline(self, participant: str, correlation_id: str, due_at: datetime) -> None:
        conn = await self._connection()
        tenant = write_tenant()
        async with self._lock:
            await conn.execute(
                "INSERT OR REPLACE INTO choreography_deadlines"
                " (tenant_id, participant, correlation_id, due_at, claimed_until)"
                " SELECT ?, ?, ?, ?, NULL WHERE NOT EXISTS (SELECT 1 FROM choreography_transactions"
                "  WHERE tenant_id = ? AND participant = ? AND correlation_id = ?)",
                (
                    tenant,
                    participant,
                    correlation_id,
                    due_at.isoformat(),
                    tenant,
                    participant,
                    correlation_id,
                ),
            )
            await conn.commit()

    async def claim_due_deadlines(
        self, participants: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        names = list(participants)
        if not names:
            return []
        conn = await self._connection()
        marks = ", ".join("?" for _ in names)
        async with self._lock:
            cursor = await conn.execute(
                "SELECT tenant_id, participant, correlation_id, due_at FROM choreography_deadlines"
                f" WHERE participant IN ({marks}) AND due_at <= ?"
                " AND (claimed_until IS NULL OR claimed_until <= ?) ORDER BY due_at LIMIT ?",
                (*names, now.isoformat(), now.isoformat(), limit),
            )
            due = [
                Deadline(tenant, participant, correlation, datetime.fromisoformat(at))
                for tenant, participant, correlation, at in await cursor.fetchall()
            ]
            await conn.executemany(
                "UPDATE choreography_deadlines SET claimed_until = ?"
                " WHERE tenant_id = ? AND participant = ? AND correlation_id = ?",
                [
                    ((now + lease).isoformat(), d.tenant_id, d.participant, d.correlation_id)
                    for d in due
                ],
            )
            await conn.commit()
        return due

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
