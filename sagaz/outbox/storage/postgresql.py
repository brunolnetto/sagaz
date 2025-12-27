"""
PostgreSQL Outbox Storage - Production-ready outbox storage using PostgreSQL.

Uses:
- asyncpg for async PostgreSQL access
- FOR UPDATE SKIP LOCKED for concurrent claim safety
- BRIN indexes for time-based queries

Usage:
    >>> from sagaz.outbox.storage import PostgreSQLOutboxStorage
    >>>
    >>> storage = PostgreSQLOutboxStorage(connection_string="postgresql://...")
    >>> await storage.initialize()
    >>>
    >>> event = OutboxEvent(saga_id="123", event_type="Test", payload={})
    >>> await storage.insert(event)
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox.storage.base import OutboxStorage, OutboxStorageError
from sagaz.outbox.types import OutboxEvent, OutboxStatus

# Check for asyncpg availability
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # pragma: no cover


# SQL for creating the outbox schema
OUTBOX_SCHEMA = """
-- Outbox table for pending messages
CREATE TABLE IF NOT EXISTS saga_outbox (
    event_id        UUID PRIMARY KEY,
    saga_id         VARCHAR(255) NOT NULL,
    aggregate_type  VARCHAR(255) NOT NULL DEFAULT 'saga',
    aggregate_id    VARCHAR(255) NOT NULL,
    event_type      VARCHAR(255) NOT NULL,
    payload         JSONB NOT NULL,
    headers         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at      TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    worker_id       VARCHAR(255),

    -- Indexes for common queries
    CONSTRAINT valid_status CHECK (
        status IN ('pending', 'claimed', 'sent', 'failed', 'dead_letter')
    )
);

-- Index for claiming pending events efficiently
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON saga_outbox (created_at)
    WHERE status = 'pending';

-- Index for finding stuck events
CREATE INDEX IF NOT EXISTS idx_outbox_claimed_at
    ON saga_outbox (claimed_at)
    WHERE status = 'claimed';

-- Index for looking up events by saga
CREATE INDEX IF NOT EXISTS idx_outbox_saga_id
    ON saga_outbox (saga_id);

-- Archive table for sent events (optional partitioning)
CREATE TABLE IF NOT EXISTS saga_outbox_archive (
    LIKE saga_outbox INCLUDING ALL
);

-- Consumer inbox table for idempotent processing
CREATE TABLE IF NOT EXISTS consumer_inbox (
    event_id            UUID PRIMARY KEY,
    consumer_name       VARCHAR(255) NOT NULL,
    source_topic        VARCHAR(255) NOT NULL,
    event_type          VARCHAR(255) NOT NULL,
    payload             JSONB NOT NULL,
    consumed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_duration_ms INTEGER
);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_consumer_inbox_cleanup
    ON consumer_inbox (consumer_name, consumed_at);
"""


class PostgreSQLOutboxStorage(OutboxStorage):
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
            raise MissingDependencyError(msg, "PostgreSQL outbox storage")  # pragma: no cover

        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:  # pragma: no cover
        """Initialize the connection pool and create schema."""
        self._pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=self.pool_min_size,
            max_size=self.pool_max_size,
        )

        # Create schema
        async with self._pool.acquire() as conn:
            await conn.execute(OUTBOX_SCHEMA)

    async def close(self) -> None:  # pragma: no cover
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _get_connection(self, connection: Any | None = None):  # pragma: no cover
        """Get a connection - either provided or from pool."""
        if connection:
            return connection
        if not self._pool:
            msg = "Storage not initialized. Call initialize() first."
            raise OutboxStorageError(msg)
        return self._pool

    async def insert(  # pragma: no cover
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Insert a new outbox event."""
        conn = self._get_connection(connection)

        query = """
            INSERT INTO saga_outbox (
                event_id, saga_id, aggregate_type, aggregate_id,
                event_type, payload, headers, status, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
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
            )
            return event

        if hasattr(conn, "execute"):
            return await _insert(conn)  # type: ignore[no-any-return]
        async with conn.acquire() as c:
            return await _insert(c)  # type: ignore[no-any-return]

    async def claim_batch(  # pragma: no cover
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

    async def update_status(  # pragma: no cover
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Update the status of an event."""
        conn = self._get_connection(connection)

        if status == OutboxStatus.SENT:
            query = """
                UPDATE saga_outbox
                SET status = $2, sent_at = NOW()
                WHERE event_id = $1
                RETURNING *
            """
            params = (event_id, status.value)
        elif status == OutboxStatus.FAILED:
            query = """
                UPDATE saga_outbox
                SET status = $2,
                    retry_count = retry_count + 1,
                    last_error = $3
                WHERE event_id = $1
                RETURNING *
            """
            params = (event_id, status.value, error_message)  # type: ignore[assignment]
        elif status == OutboxStatus.PENDING:
            query = """
                UPDATE saga_outbox
                SET status = $2,
                    worker_id = NULL,
                    claimed_at = NULL
                WHERE event_id = $1
                RETURNING *
            """
            params = (event_id, status.value)
        else:
            query = """
                UPDATE saga_outbox
                SET status = $2
                WHERE event_id = $1
                RETURNING *
            """
            params = (event_id, status.value)

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

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:  # pragma: no cover
        """Get an event by its ID."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT * FROM saga_outbox WHERE event_id = $1"

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, event_id)
            return self._row_to_event(row) if row else None

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:  # pragma: no cover
        """Get all events for a saga."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT * FROM saga_outbox WHERE saga_id = $1 ORDER BY created_at"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, saga_id)
            return [self._row_to_event(row) for row in rows]

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:  # pragma: no cover
        """Get events that appear to be stuck."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        cutoff = datetime.now(UTC) - timedelta(seconds=claimed_older_than_seconds)

        query = """
            SELECT * FROM saga_outbox
            WHERE status = 'claimed'
              AND claimed_at < $1
            ORDER BY claimed_at
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff)
            return [self._row_to_event(row) for row in rows]

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:  # pragma: no cover
        """Release stuck events back to PENDING status."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        cutoff = datetime.now(UTC) - timedelta(seconds=claimed_older_than_seconds)

        query = """
            UPDATE saga_outbox
            SET status = 'pending',
                worker_id = NULL,
                claimed_at = NULL
            WHERE status = 'claimed'
              AND claimed_at < $1
        """

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, cutoff)
            # Parse "UPDATE N" to get count
            return int(result.split()[-1])

    async def get_pending_count(self) -> int:  # pragma: no cover
        """Get count of pending events."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT COUNT(*) FROM saga_outbox WHERE status = 'pending'"

        async with self._pool.acquire() as conn:
            return await conn.fetchval(query)  # type: ignore[no-any-return]

    async def get_dead_letter_events(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:  # pragma: no cover
        """Get events in dead letter queue."""
        if not self._pool:  # pragma: no cover
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = """
            SELECT * FROM saga_outbox
            WHERE status = 'dead_letter'
            ORDER BY created_at DESC
            LIMIT $1
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
            return [self._row_to_event(row) for row in rows]

    async def archive_sent_events(
        self,
        older_than_days: int = 7,
    ) -> int:  # pragma: no cover
        """Move old sent events to archive table."""
        if not self._pool:  # pragma: no cover
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

        async with self._pool.acquire() as conn, conn.transaction():
            # Copy to archive
            insert_query = """
                    INSERT INTO saga_outbox_archive
                    SELECT * FROM saga_outbox
                    WHERE status = 'sent' AND sent_at < $1
                """
            await conn.execute(insert_query, cutoff)

            # Delete from main table
            delete_query = """
                    DELETE FROM saga_outbox
                    WHERE status = 'sent' AND sent_at < $1
                """
            result = await conn.execute(delete_query, cutoff)
            return int(result.split()[-1])

    def _row_to_event(self, row: "asyncpg.Record") -> OutboxEvent:  # pragma: no cover
        """Convert database row to OutboxEvent."""
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        headers = row["headers"]
        if isinstance(headers, str):
            headers = json.loads(headers)

        return OutboxEvent(
            event_id=str(row["event_id"]),
            saga_id=row["saga_id"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            event_type=row["event_type"],
            payload=payload,
            headers=headers,
            status=OutboxStatus(row["status"]),
            created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            sent_at=row["sent_at"],
            retry_count=row["retry_count"],
            last_error=row["last_error"],
            worker_id=row["worker_id"],
        )

    # Consumer Inbox Methods

    async def check_and_insert_inbox(
        self,
        event_id: str,
        consumer_name: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        connection: Optional["asyncpg.Connection"] = None,
    ) -> bool:  # pragma: no cover
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

    async def update_inbox_duration(
        self, event_id: str, duration_ms: int
    ) -> None:  # pragma: no cover
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

    async def cleanup_inbox(
        self, consumer_name: str, older_than_days: int
    ) -> int:  # pragma: no cover
        """
        Delete old inbox entries.

        Returns:
            Number of entries deleted
        """
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            result = await conn.execute(
                f"""
                DELETE FROM consumer_inbox
                WHERE consumer_name = $1
                  AND consumed_at < NOW() - INTERVAL '{older_than_days} days'
                """,
                consumer_name,
            )
            # Parse "DELETE N" to get count
            return int(result.split()[-1]) if result.startswith("DELETE") else 0
