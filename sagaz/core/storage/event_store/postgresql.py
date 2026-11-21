"""PostgreSQL event store (ADR-033, #57).

Events go to ``saga_events``, numbered per saga and tenant. Appends to one
stream are serialized by a transaction-scoped advisory lock, so concurrent
writers (parallel steps, several processes) never collide on a sequence.
Both tables carry ``tenant_id`` with the same row-level security policy as the
saga tables (ADR-020).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

from sagaz.core.events import SagaEvent
from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.backends.postgresql._schema_version import apply_schema
from sagaz.core.storage.backends.postgresql._tenancy import (
    POOL_OPTIONS,
    acquire_scoped,
    tenant_isolation_sql,
)
from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot

try:
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg is a core dependency
    asyncpg = None

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS saga_events (
    tenant_id   TEXT        NOT NULL DEFAULT 'default',
    saga_id     TEXT        NOT NULL,
    sequence    BIGINT      NOT NULL,
    event_id    TEXT        NOT NULL UNIQUE,
    event_type  TEXT        NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    body        JSONB       NOT NULL,
    PRIMARY KEY (tenant_id, saga_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_saga_events_type ON saga_events (event_type, occurred_at);
CREATE TABLE IF NOT EXISTS saga_event_snapshots (
    tenant_id  TEXT        NOT NULL DEFAULT 'default',
    saga_id    TEXT        NOT NULL,
    sequence   BIGINT      NOT NULL,
    state      JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, saga_id, sequence)
);
{tenant_isolation_sql("saga_events")}
{tenant_isolation_sql("saga_event_snapshots")}
"""


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgreSQLEventStore(SagaEventStore):
    """Event store in PostgreSQL.

    Args:
        connection_string: asyncpg DSN.
        pool_min_size / pool_max_size: connection pool bounds.
        **pool_kwargs: forwarded to ``asyncpg.create_pool``.
    """

    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None:
        if asyncpg is None:  # pragma: no cover - the driver is installed in tests
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL event store")
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
                async with pool.acquire() as conn:
                    await apply_schema(conn, "event_store", SCHEMA)
                self._pool = pool
        return self._pool

    async def append(self, event: SagaEvent) -> SagaEvent:
        tenant = write_tenant(event.tenant_id)
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2))",
                tenant,
                event.saga_id,
            )
            last = await conn.fetchval(
                "SELECT COALESCE(MAX(sequence), 0) FROM saga_events"
                " WHERE tenant_id = $1 AND saga_id = $2",
                tenant,
                event.saga_id,
            )
            stored = replace(event, sequence=last + 1, tenant_id=tenant)
            await conn.execute(
                "INSERT INTO saga_events"
                " (tenant_id, saga_id, sequence, event_id, event_type, occurred_at, body)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
                tenant,
                stored.saga_id,
                stored.sequence,
                stored.event_id,
                stored.event_type,
                stored.occurred_at,
                json.dumps(stored.to_dict()),
            )
        return stored

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        return await self.load_stream_after(saga_id, 0)

    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        tenant = scoped_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            rows = await conn.fetch(
                "SELECT body FROM saga_events WHERE saga_id = $1 AND sequence > $2"
                " AND ($3::text IS NULL OR tenant_id = $3) ORDER BY tenant_id, sequence",
                saga_id,
                after_sequence,
                tenant,
            )
        return [SagaEvent.from_dict(_json(row["body"])) for row in rows]

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        tenant = write_tenant(snapshot.tenant_id)
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            await conn.execute(
                "INSERT INTO saga_event_snapshots"
                " (tenant_id, saga_id, sequence, state, created_at)"
                " VALUES ($1, $2, $3, $4::jsonb, $5)"
                " ON CONFLICT (tenant_id, saga_id, sequence)"
                " DO UPDATE SET state = EXCLUDED.state, created_at = EXCLUDED.created_at",
                tenant,
                snapshot.saga_id,
                snapshot.sequence,
                json.dumps(snapshot.state),
                snapshot.created_at,
            )

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        tenant = scoped_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            row = await conn.fetchrow(
                "SELECT tenant_id, sequence, state, created_at FROM saga_event_snapshots"
                " WHERE saga_id = $1 AND ($2::text IS NULL OR tenant_id = $2)"
                " ORDER BY sequence DESC LIMIT 1",
                saga_id,
                tenant,
            )
        if row is None:
            return None
        return SagaSnapshot(
            saga_id, row["sequence"], _json(row["state"]), row["tenant_id"], row["created_at"]
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
