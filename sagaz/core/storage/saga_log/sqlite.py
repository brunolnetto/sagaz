"""SQLite saga log (ADR-041), for development, tests and single-node deployments.

Same model and semantics as PostgreSQL, without row-level security: SQLite has
one writer, so participant isolation does not apply.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.saga_log import _codec as codec
from sagaz.core.storage.saga_log._base import SagaLogStore
from sagaz.core.storage.saga_log._model import (
    TRANSACTION_MARKER,
    Activity,
    ConcurrencyError,
    Deadline,
    LogEvent,
    LogWrite,
    Participant,
    Snapshot,
    SnapshotKind,
    Transaction,
)
from sagaz.core.storage.saga_log._sqlite_delivery import SQLiteDeliveryMixin, migrate_deliveries
from sagaz.core.storage.saga_log._sqlite_export import SQLiteExportMixin
from sagaz.core.storage.saga_log._sqlite_schema import SCHEMA

# mypy reads the imports alone: no ignore is needed with or without the dependency.
if TYPE_CHECKING:
    import aiosqlite
    from aiosqlite import Connection

    from sagaz.core.storage.interfaces import OutboxStorage
else:
    try:
        import aiosqlite
    except ImportError:  # pragma: no cover - aiosqlite is a dev dependency
        aiosqlite = None


def _iso(value: Any) -> Any:
    return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value


def _row(values: list[Any]) -> list[Any]:
    return [_iso(v) for v in values]


async def _write_activities(conn: Connection, tenant: str, batch: LogWrite) -> None:
    columns = codec.ACTIVITY_COLUMNS
    for activity in batch.activities:
        stored = activity
        if (
            activity.name == TRANSACTION_MARKER
            and await _marker_status(conn, tenant, activity) == "compensated"
        ):
            stored = replace(activity, status="compensated")  # tombstones stay
        await conn.execute(
            f"INSERT OR REPLACE INTO saga_activity ({', '.join(columns)})"
            f" VALUES ({', '.join('?' for _ in columns)})",
            _row(codec.activity_values(stored, tenant)),
        )


async def _write_deadlines(conn: Connection, tenant: str, batch: LogWrite) -> None:
    if batch.deadline is not None:
        d = batch.deadline
        await conn.execute(
            "INSERT OR REPLACE INTO saga_deadline"
            " (tenant_id, transaction_id, owner, due_at, claimed_until)"
            " VALUES (?, ?, ?, ?, NULL)",
            (tenant, d.transaction_id, d.owner, _iso(d.due_at)),
        )
    for transaction_id, owner in batch.clear_deadlines:
        await conn.execute(
            "DELETE FROM saga_deadline WHERE tenant_id = ? AND transaction_id = ? AND owner = ?",
            (tenant, transaction_id, owner),
        )


async def _write_outbox(conn: Connection, tenant: str, batch: LogWrite) -> None:
    for message in batch.publish:
        await conn.execute(
            "INSERT INTO outbox_events (event_id, saga_id, event_type, payload, status,"
            " created_at, aggregate_type, aggregate_id, headers, partition_key, tenant_id)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                message.transaction_id,
                message.event_type,
                codec.dumps(message.payload),
                _iso(datetime.now(UTC)),
                message.aggregate_type,
                message.transaction_id,
                codec.dumps({"log_event_id": message.log_event_id}),
                message.partition_key,
                tenant,
            ),
        )


async def _marker_status(conn: Connection, tenant: str, activity: Activity) -> str | None:
    cursor = await conn.execute(
        "SELECT status FROM saga_activity"
        " WHERE tenant_id = ? AND transaction_id = ? AND activity_id = ?",
        (tenant, activity.transaction_id, activity.activity_id),
    )
    row = await cursor.fetchone()
    return None if row is None else str(row[0])


async def _ended(conn: Connection, tenant: str, transaction_id: str, batch: LogWrite) -> bool:
    cursor = await conn.execute(
        "SELECT 1 FROM saga_activity WHERE tenant_id = ? AND transaction_id = ?"
        " AND participant = ? AND name = ? AND status IN ('completed', 'compensated')",
        (tenant, transaction_id, batch.guard, TRANSACTION_MARKER),
    )
    return await cursor.fetchone() is not None


def _tenant_clause() -> tuple[str, tuple[str, ...]]:
    tenant = scoped_tenant()
    return ("1 = 1", ()) if tenant is None else ("tenant_id = ?", (tenant,))


class SQLiteSagaLogStore(SQLiteDeliveryMixin, SQLiteExportMixin, SagaLogStore):
    def __init__(self, db_path: str = ":memory:") -> None:
        if aiosqlite is None:  # pragma: no cover - the driver is installed in tests
            msg = "aiosqlite"
            raise MissingDependencyError(msg, "SQLite saga log")
        self.db_path = db_path
        self._conn: Connection | None = None
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def _connection(self) -> Connection:
        # Initialized once, and published only when ready: a concurrent caller
        # must neither open a second connection nor write while the outbox DDL
        # holds an open transaction.
        conn = self._conn
        if conn is None:
            async with self._init_lock:
                conn = self._conn
                if conn is None:
                    conn = await aiosqlite.connect(self.db_path)
                    conn.row_factory = aiosqlite.Row
                    await conn.executescript(SCHEMA)
                    await migrate_deliveries(conn)
                    await conn.commit()
                    await self._init_outbox(conn)
                    self._conn = conn
        return conn

    @staticmethod
    async def _init_outbox(conn: Connection) -> None:
        """Create the ``SQLiteOutboxStorage`` table on this connection (same DDL)."""
        from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

        schema = SQLiteOutboxStorage.__new__(SQLiteOutboxStorage)
        schema._conn = conn
        await schema._init_schema()

    def outbox_storage(self) -> OutboxStorage:
        """The outbox on this log's connection and write lock (works for ``:memory:`` too)."""
        from sagaz.core.storage.saga_log._sqlite_outbox import SharedSQLiteOutboxStorage

        return SharedSQLiteOutboxStorage(self)

    # -- writes ------------------------------------------------------------------

    async def write(self, batch: LogWrite) -> list[LogEvent]:
        tenant = write_tenant()
        conn = await self._connection()
        async with self._lock:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                stored = await self._write(conn, tenant, batch)
            except BaseException:
                await conn.rollback()
                raise
            await conn.commit()
        return stored

    async def _write(self, conn: Connection, tenant: str, batch: LogWrite) -> list[LogEvent]:
        columns: tuple[str, ...]
        ended = {t for t in batch.guarded_transactions() if await _ended(conn, tenant, t, batch)}
        batch.drop_guarded(ended)
        if batch.transaction is not None:
            columns = codec.TRANSACTION_COLUMNS
            await conn.execute(
                f"INSERT OR IGNORE INTO saga_transaction ({', '.join(columns)})"
                f" VALUES ({', '.join('?' for _ in columns)})",
                _row(codec.transaction_values(batch.transaction, tenant)),
            )
        if batch.status is not None:
            await self._apply_status(conn, tenant, batch)
        stored = []
        for event in batch.events:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM saga_log_event"
                " WHERE tenant_id = ? AND transaction_id = ?",
                (tenant, event.transaction_id),
            )
            row = await cursor.fetchone()  # an aggregate: always one row
            last = row[0] if row else 0
            columns = codec.EVENT_COLUMNS
            await conn.execute(
                f"INSERT INTO saga_log_event ({', '.join(columns)})"  # nosec B608 - only constant SQL fragments are interpolated; values are bound parameters
                f" VALUES ({', '.join('?' for _ in columns)})",
                _row(codec.event_values(event, tenant, last + 1)),
            )
            stored.append(replace(event, tenant_id=tenant, sequence=last + 1))
        await _write_activities(conn, tenant, batch)
        await _write_deadlines(conn, tenant, batch)
        await _write_outbox(conn, tenant, batch)
        return stored

    async def _apply_status(self, conn: Connection, tenant: str, batch: LogWrite) -> None:
        change = batch.status
        assert change is not None
        cursor = await conn.execute(
            "UPDATE saga_transaction SET status = ?, ended_at = COALESCE(?, ended_at),"
            " context = COALESCE(?, context), version = version + 1, updated_at = ?"
            " WHERE tenant_id = ? AND transaction_id = ? AND version = ?",
            (
                change.status,
                _iso(change.ended_at),
                None if change.context is None else codec.dumps(change.context),
                _iso(datetime.now(UTC)),
                tenant,
                change.transaction_id,
                change.expected_version,
            ),
        )
        if cursor.rowcount != 1:
            msg = f"Transaction {change.transaction_id} is not at version {change.expected_version}"
            raise ConcurrencyError(msg)

    async def register_participant(self, participant: Participant) -> None:
        conn = await self._connection()
        async with self._lock:
            await conn.execute(
                "INSERT OR REPLACE INTO saga_participant (tenant_id, name, region, owner, db_role)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    write_tenant(),
                    participant.name,
                    participant.region,
                    participant.owner,
                    participant.db_role,
                ),
            )
            await conn.commit()

    async def claim_delivery(self, participant: str, event_id: str) -> bool:
        conn = await self._connection()
        async with self._lock:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO saga_delivery (tenant_id, participant, event_id, consumed_at)"
                " VALUES (?, ?, ?, ?)",
                (write_tenant(), participant, event_id, _iso(datetime.now(UTC))),
            )
            await conn.commit()
        return bool(cursor.rowcount == 1)

    async def save_snapshot(self, snapshot: Snapshot) -> None:
        conn = await self._connection()
        async with self._lock:
            await conn.execute(
                "INSERT OR REPLACE INTO saga_snapshot"
                " (tenant_id, transaction_id, kind, sequence, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    write_tenant(),
                    snapshot.transaction_id,
                    str(snapshot.kind),
                    snapshot.sequence,
                    codec.dumps(snapshot.state),
                    _iso(snapshot.created_at),
                ),
            )
            await conn.commit()

    async def claim_due_deadlines(
        self, owners: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        names = list(owners)
        if not names:
            return []
        conn = await self._connection()
        marks = ", ".join("?" for _ in names)
        async with self._lock:
            cursor = await conn.execute(
                "SELECT * FROM saga_deadline"  # nosec B608 - only constant SQL fragments are interpolated; values are bound parameters
                f" WHERE owner IN ({marks}) AND due_at <= ?"
                " AND (claimed_until IS NULL OR claimed_until <= ?) ORDER BY due_at LIMIT ?",
                (*names, _iso(now), _iso(now), limit),
            )
            due = [codec.to_deadline(r) for r in await cursor.fetchall()]
            await conn.executemany(
                "UPDATE saga_deadline SET claimed_until = ?"
                " WHERE tenant_id = ? AND transaction_id = ? AND owner = ?",
                [(_iso(now + lease), d.tenant_id, d.transaction_id, d.owner) for d in due],
            )
            await conn.commit()
        return due

    # -- reads -------------------------------------------------------------------

    async def _fetch(self, sql: str, *args: Any) -> list[Any]:
        conn = await self._connection()
        clause, tenant = _tenant_clause()
        cursor = await conn.execute(sql.replace("{tenant}", clause), (*tenant, *args))
        return list(await cursor.fetchall())

    async def get_transaction(self, transaction_id: str) -> Transaction | None:
        rows = await self._fetch(
            "SELECT * FROM saga_transaction WHERE {tenant} AND transaction_id = ?"
            " ORDER BY tenant_id LIMIT 1",
            transaction_id,
        )
        return codec.to_transaction(rows[0]) if rows else None

    async def list_transactions(
        self,
        *,
        flow: str | None = None,
        coordination: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[Transaction]:
        rows = await self._fetch(
            "SELECT * FROM saga_transaction WHERE {tenant}"
            " AND (? IS NULL OR flow = ?) AND (? IS NULL OR coordination = ?)"
            " AND (? IS NULL OR status = ?) ORDER BY started_at DESC LIMIT ?",
            flow,
            flow,
            coordination and str(coordination),
            coordination and str(coordination),
            status,
            status,
            limit,
        )
        return [codec.to_transaction(r) for r in rows]

    async def activities(self, transaction_id: str) -> list[Activity]:
        rows = await self._fetch(
            "SELECT * FROM saga_activity WHERE {tenant} AND transaction_id = ?"
            " ORDER BY started_at IS NULL, started_at, activity_id",
            transaction_id,
        )
        return [codec.to_activity(r) for r in rows]

    async def events(self, transaction_id: str, after_sequence: int = 0) -> list[LogEvent]:
        rows = await self._fetch(
            "SELECT * FROM saga_log_event WHERE {tenant} AND transaction_id = ?"
            " AND sequence > ? ORDER BY tenant_id, sequence",
            transaction_id,
            after_sequence,
        )
        return [codec.to_event(r) for r in rows]

    async def latest_snapshot(
        self, transaction_id: str, kind: SnapshotKind = SnapshotKind.PROJECTION
    ) -> Snapshot | None:
        rows = await self._fetch(
            "SELECT * FROM saga_snapshot WHERE {tenant} AND transaction_id = ?"
            " AND kind = ? ORDER BY sequence DESC LIMIT 1",
            transaction_id,
            str(kind),
        )
        return codec.to_snapshot(rows[0]) if rows else None

    async def participants(self) -> list[Participant]:
        rows = await self._fetch("SELECT * FROM saga_participant WHERE {tenant} ORDER BY name")
        return [codec.to_participant(r) for r in rows]

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
