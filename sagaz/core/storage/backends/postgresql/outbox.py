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
from typing import Any, Optional, cast

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.postgresql._outbox_dlq import PostgreSQLOutboxDeadLetterMixin
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

        # Create schema
        async with self._pool.acquire() as conn:
            await conn.execute(OUTBOX_SCHEMA)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _get_connection(self, connection: Any | None = None):
        """Get a connection - either provided or from pool."""
        if connection:
            return connection
        if not self._pool:
            msg = "Storage not initialized. Call initialize() first."
            raise OutboxStorageError(msg)
        return self._pool

    async def insert(
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Insert a new outbox event."""
        conn = self._get_connection(connection)

        query = """
            INSERT INTO saga_outbox (
                event_id, saga_id, aggregate_type, aggregate_id,
                event_type, payload, headers, status, created_at,
                claimed_at, sent_at, retry_count, last_error, worker_id,
                dead_letter_at, dead_letter_reason, error_type, error_classification,
                error_fingerprint, replay_count, routing_key, partition_key
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
            )
        """

        async def _insert(c):
            await c.execute(
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
            )
            return event

        if hasattr(conn, "execute"):
            return await _insert(conn)  # type: ignore[no-any-return]
        async with conn.acquire() as c:
            return await _insert(c)  # type: ignore[no-any-return]

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim a batch of pending events for processing."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)

        # Use FOR UPDATE SKIP LOCKED for concurrency safety
        query = """
            WITH claimed AS (
                SELECT event_id
                FROM saga_outbox
                WHERE status = 'pending'
                  AND created_at <= $1
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

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff, batch_size, worker_id)
            return [self._row_to_event(row) for row in rows]

    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
        event: OutboxEvent | None = None,
    ) -> OutboxEvent:
        """Update the status of an event."""
        conn = self._get_connection(connection)
        query, params = self._build_update_status_query(event_id, status, error_message, event)

        async def _update(c):
            row = await c.fetchrow(query, *params)
            if not row:
                msg = f"Event {event_id} not found"
                raise OutboxStorageError(msg)
            return self._row_to_event(row)

        if hasattr(conn, "fetchrow"):
            return await _update(conn)  # type: ignore[no-any-return]
        async with conn.acquire() as c:
            return await _update(c)  # type: ignore[no-any-return]

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get an event by ID from active or archived storage."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM saga_outbox WHERE event_id = $1",
                event_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM saga_outbox_archive WHERE event_id = $1",
                    event_id,
                )
            return self._row_to_event(row) if row else None

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events for a saga."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT * FROM saga_outbox WHERE saga_id = $1 ORDER BY created_at"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, saga_id)
            return [self._row_to_event(row) for row in rows]

    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT COUNT(*) FROM saga_outbox WHERE status = 'pending'"

        async with self._pool.acquire() as conn:
            return await conn.fetchval(query)  # type: ignore[no-any-return]

    # Consumer Inbox Methods

    async def check_and_insert_inbox(
        self,
        event_id: str,
        consumer_name: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        connection: Optional["asyncpg.Connection"] = None,
    ) -> bool:
        """
        Check if event was already processed and insert if not.

        Args:
            event_id: Event identifier
            consumer_name: Consumer service name
            source_topic: Source topic/queue
            event_type: Event type
            payload: Event payload
            connection: Optional connection for transactions

        Returns:
            True if duplicate (already processed), False if new
        """

        async def _execute(conn):
            try:
                await conn.execute(
                    """
                    INSERT INTO consumer_inbox (
                        event_id, consumer_name, source_topic,
                        event_type, payload, consumed_at
                    )
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    event_id,
                    consumer_name,
                    source_topic,
                    event_type,
                    json.dumps(payload),
                )
                return False  # Not a duplicate
            except asyncpg.UniqueViolationError:
                return True  # Duplicate

        if connection:
            return await _execute(connection)  # type: ignore[no-any-return]
        async with self._pool.acquire() as conn, conn.transaction():  # type: ignore[union-attr]
            return await _execute(conn)  # type: ignore[no-any-return]

    async def update_inbox_duration(self, event_id: str, duration_ms: int) -> None:
        """Update processing duration for an event."""
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(
                """
                UPDATE consumer_inbox
                SET processing_duration_ms = $1
                WHERE event_id = $2
                """,
                duration_ms,
                event_id,
            )

    async def cleanup_inbox(self, consumer_name: str, older_than_days: int) -> int:
        """
        Delete old inbox entries.

        Returns:
            Number of entries deleted
        """
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            result = await conn.execute(
                """
                DELETE FROM consumer_inbox
                WHERE consumer_name = $1
                AND consumed_at < NOW() - make_interval(days => $2)
                """,
                consumer_name,
                older_than_days,
            )
            # Parse "DELETE N" to get count
            return int(result.split()[-1]) if result.startswith("DELETE") else 0
