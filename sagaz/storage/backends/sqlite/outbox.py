"""
SQLite Outbox Storage Backend.

Provides lightweight embedded outbox storage using SQLite.
Ideal for local development, testing, and single-process applications.

Usage:
    >>> from sagaz.storage.backends.sqlite import SQLiteOutboxStorage
    >>>
    >>> # File-based storage
    >>> storage = SQLiteOutboxStorage("./data/outbox.db")
    >>>
    >>> # In-memory storage (for testing)
    >>> storage = SQLiteOutboxStorage(":memory:")
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

try:
    import aiosqlite
    AIOSQLITE_AVAILABLE = True
except ImportError:  # pragma: no cover
    AIOSQLITE_AVAILABLE = False
    aiosqlite = None

from sagaz.exceptions import MissingDependencyError
from sagaz.outbox.types import OutboxEvent, OutboxStatus
from sagaz.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
    serialize,
    deserialize,
)

logger = logging.getLogger(__name__)


class SQLiteOutboxStorage:
    """
    SQLite-based outbox storage.
    
    Provides lightweight, embedded storage for outbox events.
    
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
        if not AIOSQLITE_AVAILABLE:  # pragma: no cover
            raise MissingDependencyError("aiosqlite", "SQLite storage")
        
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
    
    async def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._conn
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS outbox_events (
                event_id TEXT PRIMARY KEY,
                saga_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                sent_at TEXT,
                worker_id TEXT,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                aggregate_type TEXT,
                aggregate_id TEXT,
                headers TEXT,
                routing_key TEXT,
                partition_key TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status);
            CREATE INDEX IF NOT EXISTS idx_outbox_saga_id ON outbox_events(saga_id);
            CREATE INDEX IF NOT EXISTS idx_outbox_claimed_at ON outbox_events(claimed_at);
        """)
        await conn.commit()
    
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
        now = datetime.now(timezone.utc).isoformat()
        
        await conn.execute(
            """
            INSERT INTO outbox_events (
                event_id, saga_id, event_type, payload, status, created_at,
                aggregate_type, aggregate_id, headers, routing_key, partition_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.saga_id,
                event.event_type,
                serialize(event.payload),
                event.status.value,
                now,
                event.aggregate_type,
                event.aggregate_id,
                serialize(event.headers) if event.headers else None,
                event.routing_key,
                event.partition_key,
            ),
        )
        await conn.commit()
        
        return event
    
    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get event by ID."""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            "SELECT * FROM outbox_events WHERE event_id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        
        if row is None:
            return None
        
        return self._row_to_event(row)
    
    def _row_to_event(self, row: aiosqlite.Row) -> OutboxEvent:
        """Convert database row to OutboxEvent."""
        return OutboxEvent(
            event_id=row["event_id"],
            saga_id=row["saga_id"],
            event_type=row["event_type"],
            payload=deserialize(row["payload"]),
            status=OutboxStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            claimed_at=datetime.fromisoformat(row["claimed_at"]) if row["claimed_at"] else None,
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
            worker_id=row["worker_id"],
            retry_count=row["retry_count"] or 0,
            last_error=row["last_error"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            headers=deserialize(row["headers"]) if row["headers"] else None,
            routing_key=row["routing_key"],
            partition_key=row["partition_key"],
        )
    
    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection=None,
    ) -> OutboxEvent | None:
        """Update event status."""
        conn = await self._get_connection()
        now = datetime.now(timezone.utc).isoformat()
        
        sent_at = now if status == OutboxStatus.SENT else None
        
        await conn.execute(
            """
            UPDATE outbox_events
            SET status = ?, last_error = ?, sent_at = COALESCE(?, sent_at)
            WHERE event_id = ?
            """,
            (status.value, error_message, sent_at, event_id),
        )
        await conn.commit()
        
        return await self.get_by_id(event_id)
    
    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim a batch of pending events."""
        conn = await self._get_connection()
        now = datetime.now(timezone.utc)
        
        # First, select events to claim
        cursor = await conn.execute(
            """
            SELECT event_id FROM outbox_events
            WHERE status = 'pending'
            LIMIT ?
            """,
            (batch_size,),
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
            "SELECT * FROM outbox_events WHERE saga_id = ? ORDER BY created_at",
            (saga_id,),
        )
        rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]
    
    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events stuck in claimed state."""
        conn = await self._get_connection()
        cutoff = datetime.now(timezone.utc)
        
        cursor = await conn.execute(
            """
            SELECT * FROM outbox_events
            WHERE status = 'claimed'
            AND claimed_at < datetime('now', ?)
            """,
            (f"-{int(claimed_older_than_seconds)} seconds",),
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
            """
            UPDATE outbox_events
            SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                retry_count = retry_count + 1
            WHERE status = 'claimed'
            AND claimed_at < datetime('now', ?)
            """,
            (f"-{int(claimed_older_than_seconds)} seconds",),
        )
        await conn.commit()
        
        return cursor.rowcount
    
    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM outbox_events WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        
        return row[0] if row else 0
    
    async def get_dead_letter_events(self, limit: int = 100) -> list[OutboxEvent]:
        """Get events in dead letter status."""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            """
            SELECT * FROM outbox_events
            WHERE status = 'dead_letter'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        
        return [self._row_to_event(row) for row in rows]
    
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
        
        cursor = await conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'dead_letter' THEN 1 ELSE 0 END) as dead_letter
            FROM outbox_events
        """)
        row = await cursor.fetchone()
        
        return StorageStatistics(
            total_records=row["total"] or 0,
            pending_records=row["pending"] or 0,
        )
    
    async def count(self) -> int:
        """Count total events."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM outbox_events")
        row = await cursor.fetchone()
        return row[0] if row else 0
    
    async def export_all(self):
        """Export all records for transfer."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT * FROM outbox_events ORDER BY event_id")
        
        async for row in cursor:
            event = self._row_to_event(row)
            yield {
                "event_id": event.event_id,
                "saga_id": event.saga_id,
                "event_type": event.event_type,
                "payload": event.payload,
                "status": event.status.value,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
    
    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer."""
        event = OutboxEvent(
            event_id=record.get("event_id"),
            saga_id=record["saga_id"],
            event_type=record["event_type"],
            payload=record.get("payload", {}),
            status=OutboxStatus(record.get("status", "pending")),
        )
        await self.insert(event)
