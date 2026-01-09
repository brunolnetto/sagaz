"""
SQLite Saga Storage Backend.

Provides lightweight embedded storage using SQLite with async support via aiosqlite.
Ideal for local development, testing, and single-process applications.

Features:
- Zero configuration (works with file path or in-memory)
- ACID compliant transactions
- No external dependencies (SQLite is built into Python)
- Async support via aiosqlite

Usage:
    >>> from sagaz.storage.backends.sqlite import SQLiteSagaStorage
    >>>
    >>> # File-based storage
    >>> storage = SQLiteSagaStorage("./data/sagas.db")
    >>>
    >>> # In-memory storage (for testing)
    >>> storage = SQLiteSagaStorage(":memory:")
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import aiosqlite as aiosqlite_types

try:
    import aiosqlite

    AIOSQLITE_AVAILABLE = True
except ImportError:  # pragma: no cover
    AIOSQLITE_AVAILABLE = False
    aiosqlite = None  # type: ignore[assignment]

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.types import SagaStatus, SagaStepStatus
from sagaz.storage.base import SagaStorage
from sagaz.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
    deserialize,
    serialize,
)

logger = logging.getLogger(__name__)


class SQLiteSagaStorage(SagaStorage):
    """
    SQLite-based saga storage.

    Provides lightweight, embedded storage with ACID compliance.

    Attributes:
        db_path: Path to SQLite database file (or ":memory:" for in-memory)

    Example:
        >>> storage = SQLiteSagaStorage("./sagas.db")
        >>> async with storage:
        ...     await storage.save_saga_state(
        ...         saga_id="order-123",
        ...         saga_name="OrderSaga",
        ...         status=SagaStatus.EXECUTING,
        ...         steps=[],
        ...         context={"order_id": "123"}
        ...     )
    """

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize SQLite saga storage.

        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory
        """
        if not AIOSQLITE_AVAILABLE:  # pragma: no cover
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

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._conn
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS sagas (
                saga_id TEXT PRIMARY KEY,
                saga_name TEXT NOT NULL,
                status TEXT NOT NULL,
                steps TEXT NOT NULL,
                context TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sagas_status ON sagas(status);
            CREATE INDEX IF NOT EXISTS idx_sagas_name ON sagas(saga_name);
            CREATE INDEX IF NOT EXISTS idx_sagas_updated_at ON sagas(updated_at);
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

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save or update saga state."""
        conn = await self._get_connection()
        now = datetime.now(UTC).isoformat()

        status_str = status.value if isinstance(status, SagaStatus) else status

        await conn.execute(
            """
            INSERT INTO sagas (saga_id, saga_name, status, steps, context, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(saga_id) DO UPDATE SET
                saga_name = excluded.saga_name,
                status = excluded.status,
                steps = excluded.steps,
                context = excluded.context,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                saga_id,
                saga_name,
                status_str,
                serialize(steps),
                serialize(context),
                serialize(metadata) if metadata else None,
                now,
                now,
            ),
        )
        await conn.commit()

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state by ID."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            "SELECT * FROM sagas WHERE saga_id = ?",
            (saga_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return self._row_to_dict(row)

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert database row to dictionary."""
        return {
            "saga_id": row["saga_id"],
            "saga_name": row["saga_name"],
            "status": row["status"],
            "steps": deserialize(row["steps"]),
            "context": deserialize(row["context"]),
            "metadata": deserialize(row["metadata"]) if row["metadata"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state by ID."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            "DELETE FROM sagas WHERE saga_id = ?",
            (saga_id,),
        )
        await conn.commit()

        return cursor.rowcount > 0

    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sagas with optional filtering."""
        conn = await self._get_connection()

        query = "SELECT * FROM sagas WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status.value if isinstance(status, SagaStatus) else status)

        if saga_name:
            query += " AND saga_name = ?"
            params.append(saga_name)

        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def update_step_state(
        self,
        saga_id: str,
        step_name: str,
        status: SagaStepStatus,
        result: Any | None = None,
        error: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """Update a single step's state within a saga."""
        saga = await self.load_saga_state(saga_id)
        if saga is None:
            return

        steps = saga.get("steps", [])
        status_str = status.value if isinstance(status, SagaStepStatus) else status

        # Find and update the step
        for step in steps:
            if step.get("name") == step_name:
                step["status"] = status_str
                if result is not None:
                    step["result"] = result
                if error is not None:
                    step["error"] = error
                if executed_at:
                    step["executed_at"] = executed_at.isoformat()
                break

        # Save updated saga
        await self.save_saga_state(
            saga_id=saga_id,
            saga_name=saga["saga_name"],
            status=SagaStatus(saga["status"]),
            steps=steps,
            context=saga["context"],
            metadata=saga.get("metadata"),
        )

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get statistics about stored sagas."""
        conn = await self._get_connection()

        cursor = await conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'rolled_back' THEN 1 ELSE 0 END) as rolled_back,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'executing' THEN 1 ELSE 0 END) as executing
            FROM sagas
        """)
        row = await cursor.fetchone()

        return {
            "total": row["total"] or 0,
            "by_status": {
                "completed": row["completed"] or 0,
                "rolled_back": row["rolled_back"] or 0,
                "failed": row["failed"] or 0,
                "executing": row["executing"] or 0,
            },
        }

    async def cleanup_completed_sagas(
        self,
        older_than: datetime,
        statuses: list[SagaStatus] | None = None,
    ) -> int:
        """Clean up old completed sagas."""
        conn = await self._get_connection()

        if statuses is None:
            statuses = [SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK]

        status_values = [s.value for s in statuses]
        placeholders = ",".join("?" * len(status_values))

        cursor = await conn.execute(
            f"""
            DELETE FROM sagas
            WHERE status IN ({placeholders})
            AND updated_at < ?
            """,
            (*status_values, older_than.isoformat()),
        )
        await conn.commit()

        return cursor.rowcount

    async def health_check(self) -> dict[str, Any]:
        """Check storage health."""
        try:
            conn = await self._get_connection()
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()

            return {
                "status": "healthy",
                "backend": "sqlite",
                "db_path": self.db_path,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "backend": "sqlite",
            }

    async def count(self) -> int:
        """Count total sagas."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM sagas")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def export_all(self):
        """Export all records for transfer."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT * FROM sagas ORDER BY saga_id")

        async for row in cursor:
            yield self._row_to_dict(row)

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer."""
        await self.save_saga_state(
            saga_id=record["saga_id"],
            saga_name=record["saga_name"],
            status=SagaStatus(record["status"]),
            steps=record.get("steps", []),
            context=record.get("context", {}),
            metadata=record.get("metadata"),
        )
