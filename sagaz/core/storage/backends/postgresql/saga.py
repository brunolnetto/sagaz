"""
PostgreSQL storage implementation for saga state

Provides PostgreSQL-based persistent storage for saga state with ACID guarantees,
transactions, and advanced querying capabilities.

Requires: pip install asyncpg
"""

import asyncio
import json
from datetime import datetime
from typing import Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.storage._tenancy import write_tenant
from sagaz.core.storage._tenant_records import record_tenant_scope
from sagaz.core.storage.backends.postgresql._saga_maintenance import (
    _PostgreSQLSagaMaintenanceMixin,
)
from sagaz.core.storage.backends.postgresql._saga_query import (
    _PostgreSQLSagaQueryMixin,
    tenant_condition,
)
from sagaz.core.storage.backends.postgresql._saga_rows import _PostgreSQLSagaRowMixin
from sagaz.core.storage.backends.postgresql._saga_schema import SAGA_TABLES_SQL
from sagaz.core.storage.backends.postgresql._tenancy import acquire_scoped
from sagaz.core.storage.base import (
    SagaStorage,
    SagaStorageConnectionError,
    SagaStorageError,
)
from sagaz.core.types import SagaStatus, SagaStepStatus

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None


class PostgreSQLSagaStorage(
    _PostgreSQLSagaRowMixin,
    _PostgreSQLSagaQueryMixin,
    _PostgreSQLSagaMaintenanceMixin,
    SagaStorage,
):
    """
    PostgreSQL implementation of saga storage

    Uses PostgreSQL for ACID-compliant saga state storage with
    full SQL querying capabilities and referential integrity.

    Tenant isolation (ADR-020): rows carry ``tenant_id`` and sagas are keyed by
    ``(tenant_id, saga_id)``. Every connection is acquired with
    ``app.tenant_id`` set to the current scope, which row-level security
    enforces, and every query also filters by tenant explicitly. In the system
    scope, operations by saga id act on every tenant's saga with that id.

    Example:
        >>> async with PostgreSQLSagaStorage("postgresql://user:pass@localhost/db") as storage:
        ...     await storage.save_saga_state(
        ...         saga_id="order-123",
        ...         saga_name="OrderSaga",
        ...         status=SagaStatus.EXECUTING,
        ...         steps=[],
        ...         context={"order_id": "ABC123"}
        ...     )
    """

    # SQL schema for saga tables
    CREATE_TABLES_SQL = SAGA_TABLES_SQL

    def __init__(
        self, connection_string: str, pool_min_size: int = 5, pool_max_size: int = 20, **pool_kwargs
    ):
        """
        Configure the PostgreSQL saga storage backend.

        Args:
            connection_string: asyncpg-compatible DSN.
            pool_min_size: Minimum idle connections in the pool.
            pool_max_size: Maximum concurrent connections.
            **pool_kwargs: Forwarded verbatim to ``asyncpg.create_pool``.

        Raises:
            MissingDependencyError: If *asyncpg* is not installed.
        """
        if not ASYNCPG_AVAILABLE:
            msg = "asyncpg"
            raise MissingDependencyError(msg, "PostgreSQL storage backend")

        self.connection_string = connection_string
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool_kwargs = pool_kwargs
        self._pool = None
        self._lock = asyncio.Lock()

    async def _get_pool(self):
        """Get connection pool, creating if necessary"""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=self.pool_min_size,
                    max_size=self.pool_max_size,
                    **self.pool_kwargs,
                )

                # Initialize (and upgrade) the database schema
                async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
                    await conn.execute(self.CREATE_TABLES_SQL)

            except Exception as e:
                msg = f"Failed to connect to PostgreSQL: {e}"
                raise SagaStorageConnectionError(msg) from e

        return self._pool

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
        """Save saga state to PostgreSQL"""

        pool = await self._get_pool()
        tenant_id = write_tenant()

        async with acquire_scoped(pool) as conn:
            async with conn.transaction():
                # Upsert saga record
                await conn.execute(
                    """
                    INSERT INTO sagas (
                        saga_id, saga_name, status, context, metadata,
                        configuration, tenant_id, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (tenant_id, saga_id)
                    DO UPDATE SET
                        saga_name = EXCLUDED.saga_name,
                        status = EXCLUDED.status,
                        context = EXCLUDED.context,
                        metadata = EXCLUDED.metadata,
                        configuration = EXCLUDED.configuration,
                        updated_at = NOW()
                """,
                    saga_id,
                    saga_name,
                    status.value,
                    json.dumps(context),
                    json.dumps(metadata or {}),
                    json.dumps(configuration or [status.value]),
                    tenant_id,
                )

                # Delete existing steps and insert new ones
                await conn.execute(
                    "DELETE FROM saga_steps WHERE saga_id = $1 AND tenant_id = $2",
                    saga_id,
                    tenant_id,
                )

                if steps:
                    await conn.executemany(
                        """
                        INSERT INTO saga_steps
                        (saga_id, step_name, status, result, error, executed_at,
                         compensated_at, retry_count, duration_ms, tenant_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                        [self._step_params(saga_id, step, tenant_id) for step in steps],
                    )

    @staticmethod
    def _step_params(saga_id: str, step: dict[str, Any], tenant_id: str) -> list[Any]:
        """Parameters of the ``saga_steps`` insert for one step."""
        return [
            saga_id,
            step["name"],
            step.get("status", SagaStepStatus.PENDING.value),
            json.dumps(step.get("result")) if step.get("result") is not None else None,
            step.get("error"),
            step.get("executed_at"),
            step.get("compensated_at"),
            step.get("retry_count", 0),
            step.get("duration_ms"),
            tenant_id,
        ]

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state from PostgreSQL"""

        pool = await self._get_pool()
        params: list[Any] = [saga_id]
        condition = tenant_condition("tenant_id", params)

        async with acquire_scoped(pool) as conn:
            saga_row = await conn.fetchrow(
                f"""
                SELECT saga_id, saga_name, status, context, metadata,
                       configuration, created_at, updated_at, tenant_id
                FROM sagas WHERE saga_id = $1 AND {condition}
                ORDER BY tenant_id LIMIT 1
            """,
                *params,
            )

            if not saga_row:
                return None

            step_rows = await conn.fetch(
                """
                SELECT step_name, status, result, error, executed_at, compensated_at, retry_count,
                       duration_ms
                FROM saga_steps WHERE saga_id = $1 AND tenant_id = $2 ORDER BY id
            """,
                saga_id,
                self._row_tenant(saga_row),
            )

            return self._build_saga_dict(saga_row, step_rows)

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from PostgreSQL"""

        pool = await self._get_pool()
        params: list[Any] = [saga_id]
        condition = tenant_condition("tenant_id", params)

        async with acquire_scoped(pool) as conn:
            # Cascade delete will handle steps
            result = await conn.execute(
                f"DELETE FROM sagas WHERE saga_id = $1 AND {condition}", *params
            )
            return int(result.split()[-1]) > 0  # Extract affected row count

    async def update_step_state(
        self,
        saga_id: str,
        step_name: str,
        status: SagaStepStatus,
        result: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """Update individual step state"""

        pool = await self._get_pool()
        result_json = json.dumps(result) if result is not None else None
        params: list[Any] = [saga_id, step_name, status.value, result_json, error, executed_at]
        condition = tenant_condition("tenant_id", params)

        async with acquire_scoped(pool) as conn, conn.transaction():
            # Update step(s) and their sagas' timestamps
            update_result = await conn.execute(
                f"""
                    UPDATE saga_steps
                    SET status = $3, result = $4, error = $5, executed_at = $6
                    WHERE saga_id = $1 AND step_name = $2 AND {condition}
                """,
                *params,
            )

            if update_result.split()[-1] == "0":  # No rows affected
                msg = f"Step {step_name} not found in saga {saga_id}"
                raise SagaStorageError(msg)

            # Update saga timestamp
            saga_params: list[Any] = [saga_id]
            saga_condition = tenant_condition("tenant_id", saga_params)
            await conn.execute(
                f"""
                    UPDATE sagas SET updated_at = NOW() WHERE saga_id = $1 AND {saga_condition}
                """,
                *saga_params,
            )

    async def __aenter__(self):
        """Async context manager entry"""
        await self._get_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._pool:
            await self._pool.close()

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
