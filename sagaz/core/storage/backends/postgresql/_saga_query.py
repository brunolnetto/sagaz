"""Tenant filtering, listing and export for :class:`PostgreSQLSagaStorage` (ADR-020).

Row-level security already limits every query to ``app.tenant_id`` (set by
:func:`acquire_scoped`); the queries also filter by ``tenant_id`` explicitly so
isolation holds for superusers and ``BYPASSRLS`` roles, which skip RLS.
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from sagaz.core.storage._tenancy import TENANT_FIELD, scoped_tenant
from sagaz.core.storage.backends.postgresql._tenancy import acquire_scoped
from sagaz.core.types import SagaStatus


def tenant_condition(column: str, params: list[Any]) -> str:
    """SQL condition limiting ``column`` to the current tenant (``TRUE`` in the system scope).

    The tenant is appended to ``params``; the condition refers to it by position.
    """
    tenant = scoped_tenant()
    if tenant is None:
        return "TRUE"
    params.append(tenant)
    return f"{column} = ${len(params)}"


class _PostgreSQLSagaQueryMixin:
    """Saga listing and export, limited to the current scope."""

    if TYPE_CHECKING:

        async def _get_pool(self) -> Any: ...

        def _build_saga_dict(self, saga_row, step_rows) -> dict[str, Any]: ...

        @staticmethod
        def _row_tenant(saga_row) -> str: ...

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
        params: list[Any] = []
        conditions = [tenant_condition("s.tenant_id", params)]

        if status:
            params.append(status.value)
            conditions.append(f"s.status = ${len(params)}")

        if saga_name:
            params.append(f"%{saga_name}%")
            conditions.append(f"s.saga_name ILIKE ${len(params)}")

        where_clause = " AND ".join(conditions)

        params.extend([limit, offset])
        query = f"""
            SELECT
                s.tenant_id,
                s.saga_id,
                s.saga_name,
                s.status,
                s.created_at,
                s.updated_at,
                COUNT(ss.id) as step_count,
                COUNT(CASE WHEN ss.status = 'completed' THEN 1 END) as completed_steps
            FROM sagas s
            LEFT JOIN saga_steps ss ON s.tenant_id = ss.tenant_id AND s.saga_id = ss.saga_id
            WHERE {where_clause}
            GROUP BY s.tenant_id, s.saga_id, s.saga_name, s.status, s.created_at, s.updated_at
            ORDER BY s.created_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """

        async with acquire_scoped(pool) as conn:
            rows = await conn.fetch(query, *params)
            return [self._summary(row) for row in rows]

    def _summary(self, row: Any) -> dict[str, Any]:
        """Build a list summary from a row of :meth:`list_sagas`."""
        return {
            "saga_id": row["saga_id"],
            "saga_name": row["saga_name"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "step_count": row["step_count"],
            "completed_steps": row["completed_steps"],
            TENANT_FIELD: self._row_tenant(row),
        }

    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """Export all records of the current scope, each with its ``tenant_id``.

        Note: Using cursor for efficient streaming of large datasets.
        """
        pool = await self._get_pool()
        params: list[Any] = []
        condition = tenant_condition("tenant_id", params)

        async with acquire_scoped(pool) as conn:
            async with conn.transaction():
                # Stream sagas
                cursor = conn.cursor(
                    f"SELECT * FROM sagas WHERE {condition} ORDER BY saga_id, tenant_id", *params
                )

                async for row in cursor:
                    # Fetch steps for this saga (not super efficient but avoids giant joins)
                    step_rows = await conn.fetch(
                        "SELECT * FROM saga_steps WHERE tenant_id = $1 AND saga_id = $2 ORDER BY id",
                        self._row_tenant(row),
                        row["saga_id"],
                    )

                    yield self._build_saga_dict(row, step_rows)
