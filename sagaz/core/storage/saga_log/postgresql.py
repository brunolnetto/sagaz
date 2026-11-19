"""PostgreSQL saga log (ADR-041): the reference backend, shareable between services."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.backends.postgresql._outbox_schema import OUTBOX_SCHEMA
from sagaz.core.storage.backends.postgresql._schema_version import apply_schema
from sagaz.core.storage.backends.postgresql._tenancy import POOL_OPTIONS, acquire_scoped
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
from sagaz.core.storage.saga_log._pg_schema import SCHEMA_SQL

try:
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg is a core dependency
    asyncpg = None  # type: ignore[assignment]

_STREAM_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2))"
_TENANT = "($1::text IS NULL OR tenant_id = $1)"


def _placeholders(count: int, start: int = 1) -> str:
    return ", ".join(f"${i}" for i in range(start, start + count))


def _cast(columns: tuple[str, ...]) -> str:
    return ", ".join(
        f"${i}::jsonb" if c in codec.JSON_COLUMNS else f"${i}" for i, c in enumerate(columns, 1)
    )


_INSERT_TRANSACTION = (
    f"INSERT INTO saga_transaction ({', '.join(codec.TRANSACTION_COLUMNS)})"
    f" VALUES ({_cast(codec.TRANSACTION_COLUMNS)}) ON CONFLICT DO NOTHING"
)
_UPSERT_ACTIVITY = (
    f"INSERT INTO saga_activity ({', '.join(codec.ACTIVITY_COLUMNS)})"
    f" VALUES ({_cast(codec.ACTIVITY_COLUMNS)})"
    " ON CONFLICT (tenant_id, transaction_id, activity_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in codec.ACTIVITY_COLUMNS[3:] if c != "status")
    # A participant's marker never goes back from compensated to completed.
    + ", status = CASE WHEN saga_activity.name = '__transaction__'"
    " AND saga_activity.status = 'compensated' THEN 'compensated' ELSE EXCLUDED.status END"
)
_ENDED = (
    "SELECT EXISTS (SELECT 1 FROM saga_activity WHERE tenant_id = $1 AND transaction_id = $2"
    " AND participant = $3 AND name = '__transaction__' AND status IN ('completed', 'compensated'))"
)
_GUARD_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2 || '/' || $3))"
_INSERT_OUTBOX = (
    "INSERT INTO saga_outbox (event_id, saga_id, aggregate_type, aggregate_id, event_type,"
    " payload, headers, tenant_id, partition_key, log_event_id)"
    " VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)"
)
_INSERT_EVENT = (
    f"INSERT INTO saga_log_event ({', '.join(codec.EVENT_COLUMNS)})"
    f" VALUES ({_cast(codec.EVENT_COLUMNS)})"
)


class PostgreSQLSagaLogStore(SagaLogStore):
    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None:
        if asyncpg is None:  # pragma: no cover
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL saga log")
        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool_kwargs = pool_kwargs
        self._pool: Any = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> Any:
        async with self._lock:
            if self._pool is None:
                pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=self.pool_min_size,
                    max_size=self.pool_max_size,
                    **{**POOL_OPTIONS, **self.pool_kwargs},
                )
                await self._ensure_schema(pool)
                self._pool = pool
        return self._pool

    @staticmethod
    async def _ensure_schema(pool: Any) -> None:
        """Create or upgrade the schema; a service role relies on the platform's.

        In a database shared by services (ADR-041), the platform role owns the
        schema. A service role may not run DDL: it goes on if the schema exists.
        """
        try:
            async with pool.acquire() as conn:
                await apply_schema(conn, "outbox", OUTBOX_SCHEMA)  # LogWrite.publish
                await apply_schema(conn, "saga_log", SCHEMA_SQL)
        except asyncpg.exceptions.InsufficientPrivilegeError:
            async with pool.acquire() as conn:
                if await conn.fetchval("SELECT to_regclass('saga_log_event')") is None:
                    raise

    # -- writes ------------------------------------------------------------------

    async def write(self, batch: LogWrite) -> list[LogEvent]:
        tenant = write_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn, conn.transaction():
            await self._guard(conn, tenant, batch)
            if batch.transaction is not None:
                await conn.execute(
                    _INSERT_TRANSACTION, *codec.transaction_values(batch.transaction, tenant)
                )
            if batch.status is not None:
                await self._apply_status(conn, tenant, batch)
            stored = await self._append(conn, tenant, batch.events)
            for activity in batch.activities:
                await conn.execute(_UPSERT_ACTIVITY, *codec.activity_values(activity, tenant))
            if batch.deadline is not None:
                d = batch.deadline
                await conn.execute(
                    "INSERT INTO saga_deadline (tenant_id, transaction_id, owner, due_at)"
                    " VALUES ($1, $2, $3, $4) ON CONFLICT (tenant_id, transaction_id, owner)"
                    " DO UPDATE SET due_at = EXCLUDED.due_at, claimed_until = NULL",
                    tenant,
                    d.transaction_id,
                    d.owner,
                    d.due_at,
                )
            for transaction_id, owner in batch.clear_deadlines:
                await conn.execute(
                    "DELETE FROM saga_deadline"
                    " WHERE tenant_id = $1 AND transaction_id = $2 AND owner = $3",
                    tenant,
                    transaction_id,
                    owner,
                )
            for message in batch.publish:
                await conn.execute(
                    _INSERT_OUTBOX,
                    str(uuid.uuid4()),
                    message.transaction_id,
                    message.aggregate_type,
                    message.transaction_id,
                    message.event_type,
                    codec.dumps(message.payload),
                    codec.dumps({"log_event_id": message.log_event_id}),
                    tenant,
                    message.partition_key,
                    message.log_event_id,
                )
        return stored

    @staticmethod
    async def _guard(conn: Any, tenant: str, batch: LogWrite) -> None:
        """Serialize a participant's writes on a transaction and apply ``batch.guard``.

        Markers are locked too, so an action is never recorded after its
        participant ended the transaction, whatever process writes it.
        """
        keys = {
            (a.transaction_id, a.participant)
            for a in batch.activities
            if a.name == TRANSACTION_MARKER or a.participant == batch.guard
        }
        if batch.deadline is not None and batch.deadline.owner == batch.guard:
            keys.add((batch.deadline.transaction_id, batch.deadline.owner))
        for transaction_id, participant in sorted(keys):
            await conn.execute(_GUARD_LOCK, tenant, transaction_id, participant)
        ended = {
            t
            for t in batch.guarded_transactions()
            if await conn.fetchval(_ENDED, tenant, t, batch.guard)
        }
        batch.drop_guarded(ended)

    def outbox_storage(self) -> Any:
        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        return PostgreSQLOutboxStorage(self.connection_string)

    async def _apply_status(self, conn: Any, tenant: str, batch: LogWrite) -> None:
        change = batch.status
        assert change is not None
        version = await conn.fetchval(
            "UPDATE saga_transaction SET status = $3, ended_at = COALESCE($4, ended_at),"
            " context = COALESCE($5::jsonb, context), version = version + 1, updated_at = $6"
            " WHERE tenant_id = $1 AND transaction_id = $2 AND version = $7 RETURNING version",
            tenant,
            change.transaction_id,
            change.status,
            change.ended_at,
            None if change.context is None else codec.dumps(change.context),
            datetime.now(UTC),
            change.expected_version,
        )
        if version is None:
            msg = f"Transaction {change.transaction_id} is not at version {change.expected_version}"
            raise ConcurrencyError(msg)

    async def _append(self, conn: Any, tenant: str, events: list[LogEvent]) -> list[LogEvent]:
        stored: list[LogEvent] = []
        last: dict[str, int] = {}
        for event in events:
            tid = event.transaction_id
            if tid not in last:
                await conn.execute(_STREAM_LOCK, tenant, tid)
                last[tid] = await conn.fetchval(
                    "SELECT COALESCE(MAX(sequence), 0) FROM saga_log_event"
                    " WHERE tenant_id = $1 AND transaction_id = $2",
                    tenant,
                    tid,
                )
            last[tid] += 1
            await conn.execute(_INSERT_EVENT, *codec.event_values(event, tenant, last[tid]))
            stored.append(replace(event, tenant_id=tenant, sequence=last[tid]))
        return stored

    async def register_participant(self, participant: Participant) -> None:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            await conn.execute(
                "INSERT INTO saga_participant (tenant_id, name, region, owner, db_role)"
                " VALUES ($1, $2, $3, $4, $5) ON CONFLICT (tenant_id, name) DO UPDATE SET"
                " region = EXCLUDED.region, owner = EXCLUDED.owner, db_role = EXCLUDED.db_role",
                write_tenant(),
                participant.name,
                participant.region,
                participant.owner,
                participant.db_role,
            )

    async def claim_delivery(self, participant: str, event_id: str) -> bool:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            status = await conn.execute(
                "INSERT INTO saga_delivery (tenant_id, participant, event_id, consumed_at)"
                " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                write_tenant(),
                participant,
                event_id,
                datetime.now(UTC),
            )
        return bool(status == "INSERT 0 1")

    async def save_snapshot(self, snapshot: Snapshot) -> None:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            await conn.execute(
                "INSERT INTO saga_snapshot"
                " (tenant_id, transaction_id, kind, sequence, state, created_at)"
                " VALUES ($1, $2, $3, $4, $5::jsonb, $6)"
                " ON CONFLICT (tenant_id, transaction_id, kind, sequence)"
                " DO UPDATE SET state = EXCLUDED.state, created_at = EXCLUDED.created_at",
                write_tenant(),
                snapshot.transaction_id,
                str(snapshot.kind),
                snapshot.sequence,
                codec.dumps(snapshot.state),
                snapshot.created_at,
            )

    async def claim_due_deadlines(
        self, owners: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        """Claim due deadlines in every tenant (call in ``system_scope()`` under RLS)."""
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            rows = await conn.fetch(
                "UPDATE saga_deadline d SET claimed_until = $3"
                " FROM (SELECT tenant_id, transaction_id, owner FROM saga_deadline"
                "  WHERE owner = ANY($1::text[]) AND due_at <= $2"
                "  AND (claimed_until IS NULL OR claimed_until <= $2)"
                "  ORDER BY due_at LIMIT $4 FOR UPDATE SKIP LOCKED) due"
                " WHERE d.tenant_id = due.tenant_id AND d.transaction_id = due.transaction_id"
                " AND d.owner = due.owner"
                " RETURNING d.tenant_id, d.transaction_id, d.owner, d.due_at, NULL AS claimed_until",
                list(owners),
                now,
                now + lease,
                limit,
            )
        return sorted((codec.to_deadline(r) for r in rows), key=lambda d: d.due_at)

    # -- reads -------------------------------------------------------------------

    async def _fetch(self, sql: str, *args: Any) -> list[Any]:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            return list(await conn.fetch(sql, scoped_tenant(), *args))

    async def get_transaction(self, transaction_id: str) -> Transaction | None:
        rows = await self._fetch(
            f"SELECT * FROM saga_transaction WHERE {_TENANT} AND transaction_id = $2"
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
            f"SELECT * FROM saga_transaction WHERE {_TENANT}"
            " AND ($2::text IS NULL OR flow = $2) AND ($3::text IS NULL OR coordination = $3)"
            " AND ($4::text IS NULL OR status = $4) ORDER BY started_at DESC LIMIT $5",
            flow,
            None if coordination is None else str(coordination),
            status,
            limit,
        )
        return [codec.to_transaction(r) for r in rows]

    async def activities(self, transaction_id: str) -> list[Activity]:
        rows = await self._fetch(
            f"SELECT * FROM saga_activity WHERE {_TENANT} AND transaction_id = $2"
            " ORDER BY started_at NULLS LAST, activity_id",
            transaction_id,
        )
        return [codec.to_activity(r) for r in rows]

    async def events(self, transaction_id: str, after_sequence: int = 0) -> list[LogEvent]:
        rows = await self._fetch(
            f"SELECT * FROM saga_log_event WHERE {_TENANT} AND transaction_id = $2"
            " AND sequence > $3 ORDER BY tenant_id, sequence",
            transaction_id,
            after_sequence,
        )
        return [codec.to_event(r) for r in rows]

    async def latest_snapshot(
        self, transaction_id: str, kind: SnapshotKind = SnapshotKind.PROJECTION
    ) -> Snapshot | None:
        rows = await self._fetch(
            f"SELECT * FROM saga_snapshot WHERE {_TENANT} AND transaction_id = $2"
            " AND kind = $3 ORDER BY sequence DESC LIMIT 1",
            transaction_id,
            str(kind),
        )
        return codec.to_snapshot(rows[0]) if rows else None

    async def participants(self) -> list[Participant]:
        rows = await self._fetch(f"SELECT * FROM saga_participant WHERE {_TENANT} ORDER BY name")
        return [codec.to_participant(r) for r in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
