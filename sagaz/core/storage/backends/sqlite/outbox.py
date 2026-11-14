"""
SQLite Outbox Storage Backend.

Provides lightweight embedded outbox storage using SQLite.
Ideal for local development, testing, and single-process applications.

Usage:
    >>> from sagaz.core.storage.backends.sqlite import SQLiteOutboxStorage
    >>>
    >>> # File-based storage
    >>> storage = SQLiteOutboxStorage("./data/outbox.db")
    >>>
    >>> # In-memory storage (for testing)
    >>> storage = SQLiteOutboxStorage(":memory:")
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite as aiosqlite_types

try:
    import aiosqlite

    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False
    aiosqlite = None  # type: ignore[assignment]

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage._outbox_tenancy import resolve_event_tenant
from sagaz.core.storage.backends.sqlite._outbox_dlq import SQLiteOutboxDeadLetterMixin
from sagaz.core.storage.backends.sqlite._outbox_rows import SQLiteOutboxRowMappingMixin
from sagaz.core.storage.backends.sqlite._outbox_schema import SQLiteOutboxSchemaMixin
from sagaz.core.storage.backends.sqlite._outbox_status_queries import (
    SQLiteOutboxStatusQueryMixin,
)
from sagaz.core.storage.backends.sqlite._outbox_tenancy import TENANT_FILTER, tenant_params
from sagaz.core.storage.backends.sqlite._outbox_transfer import SQLiteOutboxTransferMixin
from sagaz.core.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
    serialize,
)
from sagaz.core.storage.interfaces.outbox import OutboxStorage

logger = logging.getLogger(__name__)


class SQLiteOutboxStorage(
    SQLiteOutboxSchemaMixin,
    SQLiteOutboxStatusQueryMixin,
    SQLiteOutboxDeadLetterMixin,
    SQLiteOutboxTransferMixin,
    SQLiteOutboxRowMappingMixin,
    OutboxStorage,
):
    """
    SQLite-based outbox storage.

    Provides lightweight, embedded storage for outbox events. Rows carry a
    ``tenant_id`` (ADR-020); outside the system scope every query is
    restricted to the current tenant.

    Attributes:
        db_path: Path to SQLite database file (or ":memory:" for in-memory)

    Example:
        >>> storage = SQLiteOutboxStorage("./outbox.db")
        >>> async with storage:
        ...     event = OutboxEvent(
        ...         saga_id="order-123",
        ...         event_type="OrderCreated",
        ...         payload={"order_id": "123"}
        ...     )
        ...     await storage.insert(event)
    """

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize SQLite outbox storage.

        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory
        """
        if not AIOSQLITE_AVAILABLE:
            msg = "aiosqlite"
            raise MissingDependencyError(msg, "SQLite storage")

        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize storage (create connection and schema)."""
        await self._get_connection()

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row

        if not self._initialized:
            await self._init_schema()
            self._initialized = True

        return self._conn

    async def __aenter__(self):
        """Async context manager entry."""
        await self._get_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._initialized = False

    async def insert(self, event: OutboxEvent, connection=None) -> OutboxEvent:
        """Insert an outbox event."""
        conn = await self._get_connection()
        now = datetime.now(UTC).isoformat()
        tenant_id = resolve_event_tenant(event)

        await conn.execute(
            """
            INSERT INTO outbox_events (
                event_id, saga_id, event_type, payload, status, created_at,
                claimed_at, sent_at, worker_id, retry_count, last_error,
                aggregate_type, aggregate_id, headers, routing_key, partition_key,
                dead_letter_at, dead_letter_reason, error_type, error_classification,
                error_fingerprint, replay_count, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.saga_id,
                event.event_type,
                serialize(event.payload),
                event.status.value,
                event.created_at.isoformat() if event.created_at else now,
                event.claimed_at.isoformat() if event.claimed_at else None,
                event.sent_at.isoformat() if event.sent_at else None,
                event.worker_id,
                event.retry_count,
                event.last_error,
                event.aggregate_type,
                event.aggregate_id,
                serialize(event.headers) if event.headers else None,
                event.routing_key,
                event.partition_key,
                event.dead_letter_at.isoformat() if event.dead_letter_at else None,
                event.dead_letter_reason,
                event.error_type,
                event.error_classification,
                event.error_fingerprint,
                event.replay_count,
                tenant_id,
            ),
        )
        await conn.commit()

        return event

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get event by ID."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"SELECT * FROM outbox_events WHERE event_id = ? AND {TENANT_FILTER}",
            (event_id, *tenant_params()),
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_event(row)

    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection=None,
        event: OutboxEvent | None = None,
    ) -> OutboxEvent:
        """Update event status."""
        conn = await self._get_connection()
        now = datetime.now(UTC).isoformat()
        query, params = self._build_update_status_query(event_id, status, error_message, event, now)
        await conn.execute(f"{query} AND {TENANT_FILTER}", (*params, *tenant_params()))
        await conn.commit()

        updated = await self.get_by_id(event_id)
        if updated is None:
            msg = f"Event {event_id} not found"
            raise KeyError(msg)
        return updated

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim a batch of pending events."""
        conn = await self._get_connection()
        now = datetime.now(UTC)

        # First, select events to claim
        cursor = await conn.execute(
            f"""
            SELECT event_id FROM outbox_events
            WHERE status = 'pending' AND {TENANT_FILTER}
            LIMIT ?
            """,
            (*tenant_params(), batch_size),
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        event_ids = [row["event_id"] for row in rows]
        placeholders = ",".join("?" * len(event_ids))

        # Update to claimed
        await conn.execute(
            f"""
            UPDATE outbox_events
            SET status = 'claimed', worker_id = ?, claimed_at = ?
            WHERE event_id IN ({placeholders})
            """,
            (worker_id, now.isoformat(), *event_ids),
        )
        await conn.commit()

        # Fetch the claimed events
        cursor = await conn.execute(
            f"SELECT * FROM outbox_events WHERE event_id IN ({placeholders})",
            event_ids,
        )
        rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events for a saga."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"SELECT * FROM outbox_events WHERE saga_id = ? AND {TENANT_FILTER} ORDER BY created_at",
            (saga_id, *tenant_params()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events stuck in claimed state."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"""
            SELECT * FROM outbox_events
            WHERE status = 'claimed'
            AND julianday(claimed_at) < julianday(?)
            AND {TENANT_FILTER}
            ORDER BY claimed_at
            """,
            (self._stuck_cutoff(claimed_older_than_seconds), *tenant_params()),
        )
        rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release events stuck in claimed state back to pending."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"""
            UPDATE outbox_events
            SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                retry_count = retry_count + 1
            WHERE status = 'claimed'
            AND julianday(claimed_at) < julianday(?)
            AND {TENANT_FILTER}
            """,
            (self._stuck_cutoff(claimed_older_than_seconds), *tenant_params()),
        )
        await conn.commit()

        return cursor.rowcount

    @staticmethod
    def _stuck_cutoff(claimed_older_than_seconds: float) -> str:
        """Claim time before which a claimed event counts as stuck.

        ``claimed_at`` is stored as a Python ISO-8601 string
        (``2026-01-01T07:00:00.123456+00:00``), which does not compare as text
        with SQLite's ``datetime('now')`` (``2026-01-01 07:00:00``): the ``T``
        sorts after the space, so same-day claims never matched. Both sides
        are compared through ``julianday()``, which parses either form,
        applies the UTC offset and keeps sub-second precision; a naive value
        is read as UTC, the zone every claim is written in.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=claimed_older_than_seconds)
        return cutoff.isoformat()

    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"SELECT COUNT(*) FROM outbox_events WHERE status = 'pending' AND {TENANT_FILTER}",
            tenant_params(),
        )
        row = await cursor.fetchone()

        return row[0] if row else 0

    async def health_check(self) -> HealthCheckResult:
        """Check storage health."""
        import time

        start = time.monotonic()

        try:
            conn = await self._get_connection()
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()

            pending = await self.get_pending_count()
            latency_ms = (time.monotonic() - start) * 1000

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                latency_ms=latency_ms,
                message="SQLite outbox storage is healthy",
                details={
                    "backend": "sqlite",
                    "db_path": self.db_path,
                    "pending_count": pending,
                },
            )
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"SQLite outbox storage error: {e}",
            )

    async def get_statistics(self) -> StorageStatistics:
        """Get storage statistics."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'dead_letter' THEN 1 ELSE 0 END) as dead_letter
            FROM outbox_events
            WHERE {TENANT_FILTER}
            """,
            tenant_params(),
        )
        row = await cursor.fetchone()
        if not row:
            return StorageStatistics(total_records=0, pending_records=0)

        return StorageStatistics(
            total_records=int(row["total"]) if row["total"] else 0,
            pending_records=int(row["pending"]) if row["pending"] else 0,
        )
