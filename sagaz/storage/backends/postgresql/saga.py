"""
PostgreSQL storage implementation for saga state

Provides PostgreSQL-based persistent storage for saga state with ACID guarantees,
transactions, and advanced querying capabilities.

Requires: pip install asyncpg
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.storage.base import (
    SagaStorage,
    SagaStorageConnectionError,
    SagaStorageError,
)
from sagaz.core.types import SagaStatus, SagaStepStatus

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    ASYNCPG_AVAILABLE = False  # pragma: no cover
    asyncpg = None  # pragma: no cover


class PostgreSQLSagaStorage(SagaStorage):
    """
    PostgreSQL implementation of saga storage

    Uses PostgreSQL for ACID-compliant saga state storage with
    full SQL querying capabilities and referential integrity.

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
    CREATE_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS sagas (
        saga_id VARCHAR(255) PRIMARY KEY,
        saga_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        context JSONB,
        metadata JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS saga_steps (
        id SERIAL PRIMARY KEY,
        saga_id VARCHAR(255) REFERENCES sagas(saga_id) ON DELETE CASCADE,
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        result JSONB,
        error TEXT,
        executed_at TIMESTAMP WITH TIME ZONE,
        compensated_at TIMESTAMP WITH TIME ZONE,
        retry_count INTEGER DEFAULT 0,
        UNIQUE(saga_id, step_name)
    );

    CREATE INDEX IF NOT EXISTS idx_sagas_status ON sagas(status);
    CREATE INDEX IF NOT EXISTS idx_sagas_name ON sagas(saga_name);
    CREATE INDEX IF NOT EXISTS idx_sagas_created_at ON sagas(created_at);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_saga_id ON saga_steps(saga_id);
    CREATE INDEX IF NOT EXISTS idx_saga_steps_status ON saga_steps(status);
    """

    def __init__(
        self, connection_string: str, pool_min_size: int = 5, pool_max_size: int = 20, **pool_kwargs
    ):
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

                # Initialize database schema
                async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
                    await conn.execute(self.CREATE_TABLES_SQL)

            except Exception as e:  # pragma: no cover
                msg = f"Failed to connect to PostgreSQL: {e}"  # pragma: no cover
                raise SagaStorageConnectionError(msg)  # pragma: no cover

        return self._pool

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save saga state to PostgreSQL"""

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Upsert saga record
                await conn.execute(
                    """
                    INSERT INTO sagas (saga_id, saga_name, status, context, metadata, updated_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (saga_id)
                    DO UPDATE SET
                        saga_name = EXCLUDED.saga_name,
                        status = EXCLUDED.status,
                        context = EXCLUDED.context,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                """,
                    saga_id,
                    saga_name,
                    status.value,
                    json.dumps(context),
                    json.dumps(metadata or {}),
                )

                # Delete existing steps and insert new ones
                await conn.execute("DELETE FROM saga_steps WHERE saga_id = $1", saga_id)

                if steps:
                    step_data = []
                    for step in steps:
                        step_data.append(
                            [
                                saga_id,
                                step["name"],
                                step.get("status", SagaStepStatus.PENDING.value),
                                json.dumps(step.get("result"))
                                if step.get("result") is not None
                                else None,
                                step.get("error"),
                                step.get("executed_at"),
                                step.get("compensated_at"),
                                step.get("retry_count", 0),
                            ]
                        )

                    await conn.executemany(
                        """
                        INSERT INTO saga_steps
                        (saga_id, step_name, status, result, error, executed_at, compensated_at, retry_count)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                        step_data,
                    )

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state from PostgreSQL"""

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            saga_row = await conn.fetchrow(
                """
                SELECT saga_id, saga_name, status, context, metadata, created_at, updated_at
                FROM sagas WHERE saga_id = $1
            """,
                saga_id,
            )

            if not saga_row:
                return None  # pragma: no cover

            step_rows = await conn.fetch(
                """
                SELECT step_name, status, result, error, executed_at, compensated_at, retry_count
                FROM saga_steps WHERE saga_id = $1 ORDER BY id
            """,
                saga_id,
            )

            return self._build_saga_dict(saga_row, step_rows)

    def _build_saga_dict(self, saga_row, step_rows) -> dict[str, Any]:
        """Build saga dict from database rows."""
        return {
            "saga_id": saga_row["saga_id"],
            "saga_name": saga_row["saga_name"],
            "status": saga_row["status"],
            "context": json.loads(saga_row["context"]) if saga_row["context"] else {},
            "metadata": json.loads(saga_row["metadata"]) if saga_row["metadata"] else {},
            "steps": [self._parse_step_row(row) for row in step_rows],
            "created_at": saga_row["created_at"].isoformat(),
            "updated_at": saga_row["updated_at"].isoformat(),
        }

    def _parse_step_row(self, step_row) -> dict[str, Any]:
        """Parse a step database row into a dict."""
        step_data = {
            "name": step_row["step_name"],
            "status": step_row["status"],
            "error": step_row["error"],
            "retry_count": step_row["retry_count"],
        }

        if step_row["result"]:
            step_data["result"] = self._parse_json_safe(step_row["result"])

        if step_row["executed_at"]:
            step_data["executed_at"] = step_row["executed_at"].isoformat()
        if step_row["compensated_at"]:
            step_data["compensated_at"] = step_row["compensated_at"].isoformat()

        return step_data

    def _parse_json_safe(self, value: str) -> Any:
        """Parse JSON, returning raw value on failure."""
        try:
            return json.loads(value)
        except json.JSONDecodeError:  # pragma: no cover
            return value  # pragma: no cover

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from PostgreSQL"""

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Cascade delete will handle steps
            result = await conn.execute("DELETE FROM sagas WHERE saga_id = $1", saga_id)
            return result.split()[-1] == "1"  # type: ignore[no-any-return]  # Extract affected row count

    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sagas with filtering"""

        pool = await self._get_pool()

        # Build dynamic query
        conditions: list[str] = []
        params: list[Any] = []
        param_count = 0

        if status:
            param_count += 1
            conditions.append(f"s.status = ${param_count}")
            params.append(status.value)

        if saga_name:
            param_count += 1
            conditions.append(f"s.saga_name ILIKE ${param_count}")
            params.append(f"%{saga_name}%")

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        # Add limit and offset
        param_count += 1
        params.append(limit)
        limit_param = f"${param_count}"

        param_count += 1
        params.append(offset)
        offset_param = f"${param_count}"

        query = f"""
            SELECT
                s.saga_id,
                s.saga_name,
                s.status,
                s.created_at,
                s.updated_at,
                COUNT(ss.id) as step_count,
                COUNT(CASE WHEN ss.status = 'completed' THEN 1 END) as completed_steps
            FROM sagas s
            LEFT JOIN saga_steps ss ON s.saga_id = ss.saga_id
            WHERE {where_clause}
            GROUP BY s.saga_id, s.saga_name, s.status, s.created_at, s.updated_at
            ORDER BY s.created_at DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

            results = []
            for row in rows:
                results.append(
                    {
                        "saga_id": row["saga_id"],
                        "saga_name": row["saga_name"],
                        "status": row["status"],
                        "created_at": row["created_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                        "step_count": row["step_count"],
                        "completed_steps": row["completed_steps"],
                    }
                )

            return results

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

        async with pool.acquire() as conn, conn.transaction():
            # Update step
            result_json = json.dumps(result) if result is not None else None

            update_result = await conn.execute(
                """
                    UPDATE saga_steps
                    SET status = $3, result = $4, error = $5, executed_at = $6
                    WHERE saga_id = $1 AND step_name = $2
                """,
                saga_id,
                step_name,
                status.value,
                result_json,
                error,
                executed_at,
            )

            if update_result.split()[-1] == "0":  # No rows affected  # pragma: no cover
                msg = f"Step {step_name} not found in saga {saga_id}"
                raise SagaStorageError(msg)  # pragma: no cover

            # Update saga timestamp
            await conn.execute(
                """
                    UPDATE sagas SET updated_at = NOW() WHERE saga_id = $1
                """,
                saga_id,
            )

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get storage statistics"""

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Count by status
            status_rows = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM sagas
                GROUP BY status
            """)

            status_counts = {row["status"]: row["count"] for row in status_rows}
            total_sagas = sum(status_counts.values())

            # Get database size
            db_size_row = await conn.fetchrow("SELECT pg_database_size(current_database()) as size")
            db_size = db_size_row["size"] if db_size_row else 0

            return {
                "total_sagas": total_sagas,
                "by_status": status_counts,
                "database_size_bytes": db_size,
                "database_size_human": self._format_bytes(db_size),
            }

    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        """Clean up old completed sagas"""

        if statuses is None:
            statuses = [SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK]

        pool = await self._get_pool()
        status_values = [s.value for s in statuses]

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM sagas
                WHERE status = ANY($1) AND updated_at < $2
            """,
                status_values,
                older_than,
            )

            return int(result.split()[-1])  # Extract affected row count

    async def health_check(self) -> dict[str, Any]:
        """Check storage health"""

        try:
            pool = await self._get_pool()

            async with pool.acquire() as conn:
                # Test basic query
                result = await conn.fetchval("SELECT 1")
                if result != 1:  # pragma: no cover
                    msg = "Basic query failed"  # pragma: no cover
                    raise Exception(msg)  # pragma: no cover

                # Get PostgreSQL version
                version = await conn.fetchval("SELECT version()")

                # Get connection stats
                pool_size = pool.get_size()

                return {
                    "status": "healthy",
                    "storage_type": "postgresql",
                    "postgresql_version": version.split()[1] if version else "unknown",
                    "pool_size": pool_size,
                    "timestamp": datetime.now(UTC).isoformat(),
                }

        except Exception as e:  # pragma: no cover
            return {
                "status": "unhealthy",
                "storage_type": "postgresql",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }  # pragma: no cover

    def _format_bytes(self, num_bytes: int) -> str:
        """Format bytes in human readable format"""
        size: float = float(num_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size = size / 1024.0
        return f"{size:.1f}PB"

    async def __aenter__(self):
        """Async context manager entry"""
        await self._get_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._pool:
            await self._pool.close()

    async def count(self) -> int:
        """Count total sagas."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM sagas")

    async def export_all(self):  # pragma: no cover
        """Export all records for transfer.

        Note: Using cursor for efficient streaming of large datasets.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Stream sagas
                cursor = await conn.cursor("SELECT * FROM sagas ORDER BY saga_id")

                async for row in cursor:
                    # Fetch steps for this saga (not super efficient but avoids giant joins)
                    # For better performance we could do a large join or stream steps separately
                    step_rows = await conn.fetch(
                        "SELECT * FROM saga_steps WHERE saga_id = $1 ORDER BY id",
                        row["saga_id"]
                    )

                    yield self._build_saga_dict(row, step_rows)

    async def import_record(self, record: dict[str, Any]) -> None:  # pragma: no cover
        """Import a single record from transfer."""
        await self.save_saga_state(
            saga_id=record["saga_id"],
            saga_name=record["saga_name"],
            status=SagaStatus(record["status"]),
            steps=record.get("steps", []),
            context=record.get("context", {}),
            metadata=record.get("metadata"),
        )
