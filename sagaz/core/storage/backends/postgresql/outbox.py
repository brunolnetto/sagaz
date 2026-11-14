"""
PostgreSQL Outbox Storage - Production-ready outbox storage using PostgreSQL.

Uses:
- asyncpg for async PostgreSQL access
- FOR UPDATE SKIP LOCKED for concurrent claim safety
- BRIN indexes for time-based queries

Usage:
    >>> from sagaz.core.storage.backends.postgresql import PostgreSQLOutboxStorage
    >>>
    >>> storage = PostgreSQLOutboxStorage(connection_string="postgresql://...")
    >>> await storage.initialize()
    >>>
    >>> event = OutboxEvent(saga_id="123", event_type="Test", payload={})
    >>> await storage.insert(event)
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage._outbox_tenancy import resolve_event_tenant
from sagaz.core.storage.backends.postgresql._outbox_dlq import PostgreSQLOutboxDeadLetterMixin
from sagaz.core.storage.backends.postgresql._outbox_inbox import PostgreSQLOutboxInboxMixin
from sagaz.core.storage.backends.postgresql._outbox_maintenance import (
    PostgreSQLOutboxMaintenanceMixin,
)
from sagaz.core.storage.backends.postgresql._outbox_rows import (
    PostgreSQLOutboxRowMappingMixin,
)
from sagaz.core.storage.backends.postgresql._outbox_schema import OUTBOX_SCHEMA
from sagaz.core.storage.backends.postgresql._outbox_status_queries import (
    PostgreSQLOutboxStatusQueryMixin,
)
from sagaz.core.storage.backends.postgresql._outbox_tenancy import (
    scoped_connection,
    tenant_param,
    tenant_predicate,
)
from sagaz.core.storage.backends.postgresql._outbox_transfer import (
    PostgreSQLOutboxTransferMixin,
)
from sagaz.core.storage.interfaces.outbox import OutboxStorage, OutboxStorageError

# Check for asyncpg availability
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = cast(Any, None)


class PostgreSQLOutboxStorage(
    PostgreSQLOutboxInboxMixin,
    PostgreSQLOutboxStatusQueryMixin,
    PostgreSQLOutboxMaintenanceMixin,
    PostgreSQLOutboxDeadLetterMixin,
    PostgreSQLOutboxTransferMixin,
    PostgreSQLOutboxRowMappingMixin,
    OutboxStorage,
):
    """
    PostgreSQL implementation of outbox storage.

    Features:
        - Atomic inserts within transactions
        - FOR UPDATE SKIP LOCKED for concurrent claim safety
        - Automatic schema creation
        - Connection pooling via asyncpg
        - Tenant isolation (ADR-020): a ``tenant_id`` column with row-level
          security, plus explicit tenant filters outside the system scope

    Usage:
        >>> storage = PostgreSQLOutboxStorage(
        ...     connection_string="postgresql://user:pass@localhost/db",
        ...     pool_min_size=5,
        ...     pool_max_size=20,
        ... )
        >>> await storage.initialize()
        >>>
        >>> # Insert atomically with saga state
        >>> async with pool.acquire() as conn:
        ...     async with conn.transaction():
        ...         await saga_storage.save(saga, conn=conn)
        ...         await outbox_storage.insert(event, connection=conn)
    """

    def __init__(
        self,
        connection_string: str,
        pool_min_size: int = 5,
        pool_max_size: int = 20,
    ):
        """
        Initialize PostgreSQL outbox storage.

        Args:
            connection_string: PostgreSQL connection string
            pool_min_size: Minimum pool connections
            pool_max_size: Maximum pool connections

        Raises:
            MissingDependencyError: If asyncpg is not installed
        """
        if not ASYNCPG_AVAILABLE:
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL outbox storage")

        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Initialize the connection pool and create schema."""
        self._pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=self.pool_min_size,
            max_size=self.pool_max_size,
        )

        # Create schema (including the tenant column and RLS policies)
        async with self._pool.acquire() as conn:
            await conn.execute(OUTBOX_SCHEMA)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def insert(
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Insert a new outbox event, owned by the tenant resolved for it."""
        tenant_id = resolve_event_tenant(event)

        query = """
            INSERT INTO saga_outbox (
                event_id, saga_id, aggregate_type, aggregate_id,
                event_type, payload, headers, status, created_at,
                claimed_at, sent_at, retry_count, last_error, worker_id,
                dead_letter_at, dead_letter_reason, error_type, error_classification,
                error_fingerprint, replay_count, routing_key, partition_key, tenant_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23
            )
        """

        async with scoped_connection(self._pool, connection) as conn:
            await conn.execute(
                query,
                event.event_id,
                event.saga_id,
                event.aggregate_type,
                event.aggregate_id,
                event.event_type,
                json.dumps(event.payload),
                json.dumps(event.headers),
                event.status.value,
                event.created_at,
                event.claimed_at,
                event.sent_at,
                event.retry_count,
                event.last_error,
                event.worker_id,
                event.dead_letter_at,
                event.dead_letter_reason,
                event.error_type,
                event.error_classification,
                event.error_fingerprint,
                event.replay_count,
                event.routing_key,
                event.partition_key,
                tenant_id,
            )
        return event

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim a batch of pending events (of every tenant in the system scope)."""
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)

        # Use FOR UPDATE SKIP LOCKED for concurrency safety
        query = f"""
            WITH claimed AS (
                SELECT event_id
                FROM saga_outbox
                WHERE status = 'pending'
                  AND created_at <= $1
                  AND {tenant_predicate(4)}
                ORDER BY created_at
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE saga_outbox
            SET status = 'claimed',
            worker_id = $3,
            claimed_at = NOW()
            WHERE event_id IN (SELECT event_id FROM claimed)
            RETURNING *
        """

        async with scoped_connection(self._pool) as conn:
            rows = await conn.fetch(query, cutoff, batch_size, worker_id, tenant_param())
            return [self._row_to_event(row) for row in rows]

    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
        event: OutboxEvent | None = None,
    ) -> OutboxEvent:
        """Update the status of an event of the current tenant."""
        query, params = self._build_update_status_query(event_id, status, error_message, event)
        query = query.replace(
            "WHERE event_id = $1",
            f"WHERE event_id = $1 AND {tenant_predicate(len(params) + 1)}",
        )

        async with scoped_connection(self._pool, connection) as conn:
            row = await conn.fetchrow(query, *params, tenant_param())
        if not row:
            msg = f"Event {event_id} not found"
            raise OutboxStorageError(msg)
        return self._row_to_event(row)

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get an event of the current tenant by ID from active or archived storage."""
        async with scoped_connection(self._pool) as conn:
            for table in ("saga_outbox", "saga_outbox_archive"):
                row = await conn.fetchrow(
                    f"SELECT * FROM {table} WHERE event_id = $1 AND {tenant_predicate(2)}",
                    event_id,
                    tenant_param(),
                )
                if row is not None:
                    return self._row_to_event(row)
            return None

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events of the current tenant for a saga."""
        query = (
            f"SELECT * FROM saga_outbox WHERE saga_id = $1 AND {tenant_predicate(2)} "
            "ORDER BY created_at"
        )

        async with scoped_connection(self._pool) as conn:
            rows = await conn.fetch(query, saga_id, tenant_param())
            return [self._row_to_event(row) for row in rows]

    async def get_pending_count(self) -> int:
        """Get count of pending events of the current tenant."""
        query = (
            f"SELECT COUNT(*) FROM saga_outbox WHERE status = 'pending' AND {tenant_predicate(1)}"
        )

        async with scoped_connection(self._pool) as conn:
            return await conn.fetchval(query, tenant_param())  # type: ignore[no-any-return]
