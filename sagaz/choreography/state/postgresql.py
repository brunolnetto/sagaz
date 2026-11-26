"""PostgreSQL participant state, shared by every replica of a participant (#448).

The tables are tenant-scoped with the same row-level security policy as the
saga tables (ADR-020).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.choreography.events import Event
from sagaz.choreography.state._base import COMPENSATED, COMPLETED, Deadline, ParticipantState
from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import write_tenant
from sagaz.core.storage.backends.postgresql._schema_version import apply_schema
from sagaz.core.storage.backends.postgresql._tenancy import (
    POOL_OPTIONS,
    acquire_scoped,
    tenant_isolation_sql,
)

if TYPE_CHECKING:
    from asyncpg import Pool

try:
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg is a core dependency
    asyncpg = None

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS choreography_actions (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT  NOT NULL DEFAULT 'default',
    participant    TEXT  NOT NULL,
    correlation_id TEXT  NOT NULL,
    event_id       TEXT  NOT NULL,
    body           JSONB NOT NULL,
    UNIQUE (tenant_id, participant, event_id)
);
CREATE INDEX IF NOT EXISTS idx_choreography_actions_tx
    ON choreography_actions (tenant_id, participant, correlation_id);
CREATE TABLE IF NOT EXISTS choreography_transactions (
    tenant_id      TEXT        NOT NULL DEFAULT 'default',
    participant    TEXT        NOT NULL,
    correlation_id TEXT        NOT NULL,
    state          TEXT        NOT NULL,
    ended_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, participant, correlation_id)
);
CREATE TABLE IF NOT EXISTS choreography_deadlines (
    tenant_id      TEXT        NOT NULL DEFAULT 'default',
    participant    TEXT        NOT NULL,
    correlation_id TEXT        NOT NULL,
    due_at         TIMESTAMPTZ NOT NULL,
    claimed_until  TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, participant, correlation_id)
);
CREATE INDEX IF NOT EXISTS idx_choreography_deadlines_due ON choreography_deadlines (due_at);
CREATE TABLE IF NOT EXISTS choreography_deliveries (
    tenant_id   TEXT        NOT NULL DEFAULT 'default',
    participant TEXT        NOT NULL,
    event_id    TEXT        NOT NULL,
    handled_at  TIMESTAMPTZ NOT NULL,
    claimed_until TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, participant, event_id)
);
ALTER TABLE choreography_deliveries ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ;
{tenant_isolation_sql("choreography_actions")}
{tenant_isolation_sql("choreography_transactions")}
{tenant_isolation_sql("choreography_deliveries")}
{tenant_isolation_sql("choreography_deadlines")}
"""

# Serializes record_action and finish of one transaction, so an action is
# never recorded after the transaction ended.
_TX_LOCK = "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2 || '/' || $3))"

# A delivery being handled is reserved until claimed_until; NULL means handled
# for good (every row written before #561). The claim takes the row only if it
# is new or its reservation expired; the row lock of ON CONFLICT makes it atomic.
_CLAIM = (
    "INSERT INTO choreography_deliveries"
    " (tenant_id, participant, event_id, handled_at, claimed_until) VALUES ($1, $2, $3, $4, $5)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " handled_at = EXCLUDED.handled_at, claimed_until = EXCLUDED.claimed_until"
    " WHERE choreography_deliveries.claimed_until <= $4 RETURNING 1"
)
_FINISH = (
    "INSERT INTO choreography_deliveries"
    " (tenant_id, participant, event_id, handled_at, claimed_until) VALUES ($1, $2, $3, $4, NULL)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " handled_at = EXCLUDED.handled_at, claimed_until = NULL"
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgreSQLParticipantState(ParticipantState):
    """Participant state in PostgreSQL."""

    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None:
        if asyncpg is None:  # pragma: no cover - the driver is installed in tests
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL participant state")
        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool_kwargs = pool_kwargs
        self._pool: Any = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> Pool:
        async with self._lock:
            if self._pool is None:
                pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=self.pool_min_size,
                    max_size=self.pool_max_size,
                    **{**POOL_OPTIONS, **self.pool_kwargs},
                )
                async with pool.acquire() as conn:
                    await apply_schema(conn, "choreography_state", SCHEMA)
                self._pool = pool
        return self._pool

    async def record_action(self, participant: str, event: Event) -> None:
        if not event.saga_id:
            return
        tenant = write_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn, conn.transaction():
            await conn.execute(_TX_LOCK, tenant, participant, event.saga_id)
            await conn.execute(
                "INSERT INTO choreography_actions"
                " (tenant_id, participant, correlation_id, event_id, body)"
                " SELECT $1, $2, $3, $4, $5::jsonb WHERE NOT EXISTS ("
                "  SELECT 1 FROM choreography_transactions"
                "  WHERE tenant_id = $1 AND participant = $2 AND correlation_id = $3)"
                " ON CONFLICT (tenant_id, participant, event_id) DO NOTHING",
                tenant,
                participant,
                event.saga_id,
                event.event_id,
                json.dumps(event.to_dict()),
            )

    async def finish(
        self, participant: str, correlation_id: str, *, compensated: bool
    ) -> list[Event]:
        tenant = write_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn, conn.transaction():
            await conn.execute(_TX_LOCK, tenant, participant, correlation_id)
            rows = await conn.fetch(
                "DELETE FROM choreography_actions"
                " WHERE tenant_id = $1 AND participant = $2 AND correlation_id = $3"
                " RETURNING id, body",
                tenant,
                participant,
                correlation_id,
            )
            await conn.execute(
                "DELETE FROM choreography_deadlines"
                " WHERE tenant_id = $1 AND participant = $2 AND correlation_id = $3",
                tenant,
                participant,
                correlation_id,
            )
            await conn.execute(
                "INSERT INTO choreography_transactions"
                " (tenant_id, participant, correlation_id, state, ended_at)"
                " VALUES ($1, $2, $3, $4, $5)"
                " ON CONFLICT (tenant_id, participant, correlation_id) DO UPDATE SET"
                " state = CASE WHEN EXCLUDED.state = 'compensated' THEN 'compensated'"
                " ELSE choreography_transactions.state END",
                tenant,
                participant,
                correlation_id,
                COMPENSATED if compensated else COMPLETED,
                datetime.now(UTC),
            )
        return [Event.from_dict(_json(r["body"])) for r in sorted(rows, key=lambda r: r["id"])]

    async def was_compensated(self, participant: str, correlation_id: str) -> bool:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            return bool(
                await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM choreography_transactions"
                    " WHERE tenant_id = $1 AND participant = $2 AND correlation_id = $3"
                    " AND state = 'compensated')",
                    write_tenant(),
                    participant,
                    correlation_id,
                )
            )

    async def first_delivery(self, participant: str, event_id: str) -> bool:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            status = await conn.execute(
                "INSERT INTO choreography_deliveries (tenant_id, participant, event_id, handled_at)"
                " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                write_tenant(),
                participant,
                event_id,
                datetime.now(UTC),
            )
        return bool(status == "INSERT 0 1")

    async def claim_delivery(self, participant: str, event_id: str, lease: timedelta) -> bool:
        now = datetime.now(UTC)
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            claimed = await conn.fetchval(
                _CLAIM, write_tenant(), participant, event_id, now, now + lease
            )
        return claimed is not None

    async def finish_delivery(self, participant: str, event_id: str) -> None:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            await conn.execute(_FINISH, write_tenant(), participant, event_id, datetime.now(UTC))

    async def set_deadline(self, participant: str, correlation_id: str, due_at: datetime) -> None:
        tenant = write_tenant()
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn, conn.transaction():
            await conn.execute(_TX_LOCK, tenant, participant, correlation_id)
            await conn.execute(
                "INSERT INTO choreography_deadlines"
                " (tenant_id, participant, correlation_id, due_at)"
                " SELECT $1, $2, $3, $4 WHERE NOT EXISTS ("
                "  SELECT 1 FROM choreography_transactions"
                "  WHERE tenant_id = $1 AND participant = $2 AND correlation_id = $3)"
                " ON CONFLICT (tenant_id, participant, correlation_id)"
                " DO UPDATE SET due_at = EXCLUDED.due_at, claimed_until = NULL",
                tenant,
                participant,
                correlation_id,
                due_at,
            )

    async def claim_due_deadlines(
        self, participants: Collection[str], now: datetime, lease: timedelta, limit: int = 100
    ) -> list[Deadline]:
        """Claim due deadlines in every tenant (call in ``system_scope()`` under RLS)."""
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            rows = await conn.fetch(
                "UPDATE choreography_deadlines d SET claimed_until = $3"
                " FROM (SELECT tenant_id, participant, correlation_id FROM choreography_deadlines"
                "  WHERE participant = ANY($1::text[]) AND due_at <= $2"
                "  AND (claimed_until IS NULL OR claimed_until <= $2)"
                "  ORDER BY due_at LIMIT $4 FOR UPDATE SKIP LOCKED) due"
                " WHERE d.tenant_id = due.tenant_id AND d.participant = due.participant"
                " AND d.correlation_id = due.correlation_id"
                " RETURNING d.tenant_id, d.participant, d.correlation_id, d.due_at",
                list(participants),
                now,
                now + lease,
                limit,
            )
        return [
            Deadline(r["tenant_id"], r["participant"], r["correlation_id"], r["due_at"])
            for r in sorted(rows, key=lambda r: r["due_at"])
        ]

    async def prune(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            ended = await conn.execute(
                "DELETE FROM choreography_transactions WHERE ended_at < $1", cutoff
            )
            seen = await conn.execute(
                "DELETE FROM choreography_deliveries WHERE handled_at < $1", cutoff
            )
        return int(ended.split()[-1]) + int(seen.split()[-1])

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
