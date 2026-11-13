"""Statistics, cleanup and health checks for :class:`PostgreSQLSagaStorage`."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.types import SagaStatus


class _PostgreSQLSagaMaintenanceMixin:
    """Read-only statistics, retention cleanup and health probing."""

    if TYPE_CHECKING:

        async def _get_pool(self) -> Any: ...

        def _format_bytes(self, num_bytes: int) -> str: ...

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
                if result != 1:
                    msg = "Basic query failed"
                    raise RuntimeError(msg)

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

        except Exception as e:
            return {
                "status": "unhealthy",
                "storage_type": "postgresql",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def count(self) -> int:
        """Count total sagas."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM sagas"))
