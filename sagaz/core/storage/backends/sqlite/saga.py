"""
SQLite Saga Storage Backend.

Provides lightweight embedded storage using SQLite with async support via aiosqlite.
Ideal for local development, testing, and single-process applications.

Features:
- Zero configuration (works with file path or in-memory)
- ACID compliant transactions
- No external dependencies (SQLite is built into Python)
- Async support via aiosqlite
- Tenant isolation (ADR-020): sagas are keyed by ``(tenant_id, saga_id)`` and
  every query is limited to the current tenant, except in the system scope

Usage:
    >>> from sagaz.core.storage.backends.sqlite import SQLiteSagaStorage
    >>>
    >>> # File-based storage
    >>> storage = SQLiteSagaStorage("./data/sagas.db")
    >>>
    >>> # In-memory storage (for testing)
    >>> storage = SQLiteSagaStorage(":memory:")
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
from sagaz.core.storage._tenancy import TENANT_FIELD, write_tenant
from sagaz.core.storage._tenant_records import record_tenant_scope
from sagaz.core.storage.backends.sqlite._saga_maintenance import _SQLiteSagaMaintenanceMixin
from sagaz.core.storage.backends.sqlite._saga_schema import init_saga_schema, tenant_filter
from sagaz.core.storage.base import SagaStorage
from sagaz.core.storage.core import (
    deserialize,
    serialize,
)
from sagaz.core.types import SagaStatus, SagaStepStatus

logger = logging.getLogger(__name__)


class SQLiteSagaStorage(_SQLiteSagaMaintenanceMixin, SagaStorage):
    """
    SQLite-based saga storage.

    Provides lightweight, embedded storage with ACID compliance.

    Sagas belong to the tenant of the scope that saved them (ADR-020); in the
    system scope, operations by saga id act on every tenant's saga with that id.

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

    async def _init_schema(self) -> None:
        """Initialize (and upgrade) the database schema."""
        conn = self._conn
        if conn is None:
            msg = "Connection not initialized"
            raise RuntimeError(msg)
        await init_saga_schema(conn)

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
        configuration: list[str] | None = None,
    ) -> None:
        """Save or update saga state."""
        conn = await self._get_connection()
        now = datetime.now(UTC).isoformat()

        status_str = status.value if isinstance(status, SagaStatus) else status

        await conn.execute(
            """
            INSERT INTO sagas (
                tenant_id, saga_id, saga_name, status, steps, context, metadata,
                configuration, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, saga_id) DO UPDATE SET
                saga_name = excluded.saga_name,
                status = excluded.status,
                steps = excluded.steps,
                context = excluded.context,
                metadata = excluded.metadata,
                configuration = excluded.configuration,
                updated_at = excluded.updated_at
            """,
            (
                write_tenant(),
                saga_id,
                saga_name,
                status_str,
                serialize(steps),
                serialize(context),
                serialize(metadata) if metadata else None,
                serialize(configuration or [status_str]),
                now,
                now,
            ),
        )
        await conn.commit()

    async def _load_matching(self, saga_id: str) -> list[dict[str, Any]]:
        """Visible sagas with ``saga_id`` (one per tenant in the system scope)."""
        conn = await self._get_connection()
        clause, params = tenant_filter()
        cursor = await conn.execute(
            f"SELECT * FROM sagas WHERE saga_id = ?{clause} ORDER BY tenant_id",
            (saga_id, *params),
        )
        return [self._row_to_dict(row) for row in await cursor.fetchall()]

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state by ID."""
        matches = await self._load_matching(saga_id)
        return matches[0] if matches else None

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert database row to dictionary."""
        return {
            "saga_id": row["saga_id"],
            "saga_name": row["saga_name"],
            "status": row["status"],
            "configuration": (
                deserialize(row["configuration"]) or [row["status"]]
                if row["configuration"]
                else [row["status"]]
            ),
            "steps": deserialize(row["steps"]),
            "context": deserialize(row["context"]),
            "metadata": deserialize(row["metadata"]) if row["metadata"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            TENANT_FIELD: row["tenant_id"],
        }

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state by ID."""
        conn = await self._get_connection()
        clause, params = tenant_filter()

        cursor = await conn.execute(
            f"DELETE FROM sagas WHERE saga_id = ?{clause}",
            (saga_id, *params),
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

        clause, params = tenant_filter()
        query = f"SELECT * FROM sagas WHERE 1=1{clause}"

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
        status_str = status.value if isinstance(status, SagaStepStatus) else status
        for saga in await self._load_matching(saga_id):
            steps = saga.get("steps", [])
            self._apply_step_update(steps, step_name, status_str, result, error, executed_at)

            # Save the updated saga back into its own tenant
            with record_tenant_scope(saga):
                await self.save_saga_state(
                    saga_id=saga_id,
                    saga_name=saga["saga_name"],
                    status=SagaStatus(saga["status"]),
                    steps=steps,
                    context=saga["context"],
                    metadata=saga.get("metadata"),
                )

    @staticmethod
    def _apply_step_update(
        steps: list[dict[str, Any]],
        step_name: str,
        status_str: str,
        result: Any | None,
        error: str | None,
        executed_at: datetime | None,
    ) -> None:
        """Find ``step_name`` in ``steps`` and apply the update to it."""
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

    async def export_all(self):
        """Export all records of the current scope, each with its ``tenant_id``."""
        conn = await self._get_connection()
        clause, params = tenant_filter()
        cursor = await conn.execute(
            f"SELECT * FROM sagas WHERE 1=1{clause} ORDER BY saga_id, tenant_id", params
        )

        async for row in cursor:
            yield self._row_to_dict(row)

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer, into the record's own tenant."""
        with record_tenant_scope(record):
            await self.save_saga_state(
                saga_id=record["saga_id"],
                saga_name=record["saga_name"],
                status=SagaStatus(record["status"]),
                steps=record.get("steps", []),
                context=record.get("context", {}),
                metadata=record.get("metadata"),
                configuration=record.get("configuration") or [record["status"]],
            )
