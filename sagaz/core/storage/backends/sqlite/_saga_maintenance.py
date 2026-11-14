"""Statistics, cleanup and health checks for :class:`SQLiteSagaStorage`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sagaz.core.storage._reserved import RESERVED_SAGA_LIKE
from sagaz.core.storage.backends.sqlite._saga_schema import tenant_filter
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from datetime import datetime

    import aiosqlite


class _SQLiteSagaMaintenanceMixin:
    """Status counters, retention cleanup and health probing."""

    db_path: str

    if TYPE_CHECKING:

        async def _get_connection(self) -> aiosqlite.Connection: ...

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get statistics about stored sagas."""
        conn = await self._get_connection()

        clause, params = tenant_filter()
        cursor = await conn.execute(
            f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'rolled_back' THEN 1 ELSE 0 END) as rolled_back,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'executing' THEN 1 ELSE 0 END) as executing
            FROM sagas WHERE 1=1{clause}
        """,
            params,
        )
        row = await cursor.fetchone()
        if not row:
            return {
                "total": 0,
                "by_status": {"completed": 0, "rolled_back": 0, "failed": 0, "executing": 0},
            }

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
        clause, params = tenant_filter()

        cursor = await conn.execute(
            f"""
            DELETE FROM sagas
            WHERE status IN ({placeholders})
            AND updated_at < ?
            AND saga_name NOT LIKE ? ESCAPE '\\'{clause}
            """,
            (*status_values, older_than.isoformat(), RESERVED_SAGA_LIKE, *params),
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
        clause, params = tenant_filter()
        cursor = await conn.execute(f"SELECT COUNT(*) FROM sagas WHERE 1=1{clause}", params)
        row = await cursor.fetchone()
        return row[0] if row else 0
