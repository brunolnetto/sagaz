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
from typing import Any, Optional

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.outbox.types import OutboxEvent, OutboxStatus, ReplayLoopError
from sagaz.core.storage.interfaces.outbox import OutboxStorage, OutboxStorageError

# Check for asyncpg availability
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None


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
    dead_letter_at  TIMESTAMPTZ,
    dead_letter_reason TEXT,
    error_type      VARCHAR(255),
    error_classification VARCHAR(255),
    error_fingerprint VARCHAR(255),
    replay_count    INTEGER NOT NULL DEFAULT 0,

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

ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_type VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_classification VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS error_fingerprint VARCHAR(255);
ALTER TABLE saga_outbox ADD COLUMN IF NOT EXISTS replay_count INTEGER NOT NULL DEFAULT 0;
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
                retry_count, last_error, worker_id, dead_letter_at, dead_letter_reason,
                error_type, error_classification, error_fingerprint, replay_count
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17, $18
            )
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
                event.retry_count,
                event.last_error,
                event.worker_id,
                event.dead_letter_at,
                event.dead_letter_reason,
                event.error_type,
                event.error_classification,
                event.error_fingerprint,
                event.replay_count,
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

    def _build_update_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        if status == OutboxStatus.SENT:
            return self._sent_status_query(event_id, status)
        if status == OutboxStatus.FAILED:
            return self._failed_status_query(event_id, status, error_message, event)
        if status == OutboxStatus.DEAD_LETTER:
            return self._dead_letter_status_query(event_id, status, error_message, event)
        if status == OutboxStatus.PENDING:
            return self._pending_status_query(event_id, status, event)
        return self._generic_status_query(event_id, status)

    def _sent_status_query(self, event_id: str, status: OutboxStatus) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2, sent_at = NOW()
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value),
        )

    def _failed_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                retry_count = retry_count + 1,
                last_error = $3,
                error_type = $4,
                error_classification = $5,
                error_fingerprint = $6
                WHERE event_id = $1
                RETURNING *
            """,
            (
                event_id,
                status.value,
                error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
            ),
        )

    def _dead_letter_status_query(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                    dead_letter_at = COALESCE($3, NOW()),
                    dead_letter_reason = COALESCE($4, last_error, dead_letter_reason, 'max_retries_exceeded'),
                    error_type = COALESCE($5, error_type),
                    error_classification = COALESCE($6, error_classification),
                    error_fingerprint = COALESCE($7, error_fingerprint)
                WHERE event_id = $1
                RETURNING *
            """,
            (
                event_id,
                status.value,
                event.dead_letter_at if event else None,
                event.dead_letter_reason if event else error_message,
                event.error_type if event else None,
                event.error_classification if event else None,
                event.error_fingerprint if event else None,
            ),
        )

    def _pending_status_query(
        self, event_id: str, status: OutboxStatus, event: OutboxEvent | None
    ) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2,
                worker_id = NULL,
                claimed_at = NULL,
                dead_letter_at = NULL,
                dead_letter_reason = NULL,
                replay_count = COALESCE($3, replay_count)
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value, event.replay_count if event else None),
        )

    def _generic_status_query(self, event_id: str, status: OutboxStatus) -> tuple[str, tuple[Any, ...]]:
        return (
            """
                UPDATE saga_outbox
                SET status = $2
                WHERE event_id = $1
                RETURNING *
            """,
            (event_id, status.value),
        )

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get an event by its ID."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        query = "SELECT * FROM saga_outbox WHERE event_id = $1"

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, event_id)
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

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
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
    ) -> int:
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

    async def get_pending_count(self) -> int:
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
    ) -> list[OutboxEvent]:
        """Get events in dead letter queue."""
        if not self._pool:
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
    ) -> int:
        """Move old sent events to archive table."""
        if not self._pool:
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

    def _row_to_event(self, row: "asyncpg.Record") -> OutboxEvent:
        """Convert database row to OutboxEvent."""
        def _row_value(key: str, default=None):
            if hasattr(row, "__contains__") and key in row:
                return row[key]
            if hasattr(row, "get"):
                return row.get(key, default)
            return default

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
            dead_letter_at=_row_value("dead_letter_at"),
            dead_letter_reason=_row_value("dead_letter_reason"),
            error_type=_row_value("error_type"),
            error_classification=_row_value("error_classification"),
            error_fingerprint=_row_value("error_fingerprint"),
            replay_count=_row_value("replay_count", 0) or 0,
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
                AND consumed_at < NOW() - ($2::text || ' days')::interval
                """,
                consumer_name,
                older_than_days,
            )
            # Parse "DELETE N" to get count
            return int(result.split()[-1]) if result.startswith("DELETE") else 0

    async def count(self) -> int:
        """Count total events."""
        if not self._pool:
            # If not initialized, maybe zero? Or raise error?
            # Assuming initialized for now as it's required for other ops
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM saga_outbox"))

    async def export_all(self):
        """Export all records for transfer."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                try:
                    cursor = await conn.cursor("SELECT * FROM saga_outbox ORDER BY event_id")
                    async for row in cursor:
                        event = self._row_to_event(row)
                        yield {
                            "event_id": event.event_id,
                            "saga_id": event.saga_id,
                            "event_type": event.event_type,
                            "payload": event.payload,
                            "status": event.status.value,
                            "created_at": event.created_at.isoformat()
                            if event.created_at
                            else None,
                            "retry_count": event.retry_count,
                            "last_error": event.last_error,
                            "dead_letter_at": event.dead_letter_at.isoformat()
                            if event.dead_letter_at
                            else None,
                            "dead_letter_reason": event.dead_letter_reason,
                            "error_type": event.error_type,
                            "error_classification": event.error_classification,
                            "error_fingerprint": event.error_fingerprint,
                            "replay_count": event.replay_count,
                        }
                except Exception:  # pylint: disable=try-except-raise
                    # Transaction rollback is automatic with context manager
                    raise

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer."""
        # Using insert which is already idempotent-ish or effectively so
        event = OutboxEvent(
            event_id=str(record.get("event_id")),
            saga_id=record["saga_id"],
            event_type=record["event_type"],
            payload=record.get("payload", {}),
            status=OutboxStatus(record.get("status", "pending")),
            retry_count=int(record.get("retry_count", 0) or 0),
            last_error=record.get("last_error"),
            dead_letter_at=datetime.fromisoformat(record["dead_letter_at"])
            if record.get("dead_letter_at")
            else None,
            dead_letter_reason=record.get("dead_letter_reason"),
            error_type=record.get("error_type"),
            error_classification=record.get("error_classification"),
            error_fingerprint=record.get("error_fingerprint"),
            replay_count=int(record.get("replay_count", 0) or 0),
        )
        await self.insert(event)

    async def requeue_dead_letter_event(self, event_id: str, force: bool = False) -> OutboxEvent:
        """Move a dead-letter event back to PENDING for replay."""
        event = await self.get_by_id(event_id)
        if event is None:
            msg = f"Event {event_id} not found"
            raise KeyError(msg)

        max_replays = 3
        if not force and event.replay_count >= max_replays:
            raise ReplayLoopError(
                event_id=event_id,
                replay_count=event.replay_count,
                max_replays=max_replays,
            )

        event.replay_count += 1
        event.retry_count = 0
        event.dead_letter_at = None
        event.dead_letter_reason = None
        event.worker_id = None
        event.claimed_at = None
        return await self.update_status(event_id, OutboxStatus.PENDING, event=event)

    async def purge_dead_letter_events(self, older_than: timedelta | None = None) -> int:
        """Permanently remove dead-letter events."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            if older_than is None:
                result = await conn.execute("DELETE FROM saga_outbox WHERE status = 'dead_letter'")
            else:
                cutoff = datetime.now(UTC) - older_than
                result = await conn.execute(
                    """
                    DELETE FROM saga_outbox
                    WHERE status = 'dead_letter'
                    AND dead_letter_at IS NOT NULL
                    AND dead_letter_at < $1
                    """,
                    cutoff,
                )
            return int(result.split()[-1]) if result.startswith("DELETE") else 0
