"""PostgreSQL row-level security for tenant isolation (ADR-020).

Every tenant-owned table gets a ``tenant_id`` column and an RLS policy that
compares it with the ``app.tenant_id`` setting. :func:`acquire_scoped` sets that
setting from the current scope each time a pooled connection is acquired, so a
connection never carries a previous task's tenant.

Setting it costs a round trip, which single-tenant deployments should not pay
on every acquisition (#405). sagaz therefore remembers which connections are
known to be at the default tenant: pools it creates reset connections to the
default tenant on release (in the same round trip as asyncpg's own reset, see
:data:`POOL_OPTIONS`), and :func:`apply_scope` records every value it sets.
For the default tenant on such a connection the ``set_config`` is skipped;
any other tenant, and any connection sagaz knows nothing about, is set as
before.

RLS is not applied to superusers or roles with ``BYPASSRLS``: run the
application with an ordinary role for the database to enforce isolation. The
backends also filter by ``tenant_id`` explicitly, so isolation holds even then.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakSet

from sagaz.core.tenant import DEFAULT_TENANT, current_tenant_id

#: Name of the RLS policy created on each tenant-owned table.
POLICY_NAME = "sagaz_tenant_isolation"

# The policy admits the system scope ('*') and otherwise only the session's
# tenant; an unset setting means the default tenant.
_SCOPE_PREDICATE = (
    "(current_setting('app.tenant_id', true) = '*' "
    "OR tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default'))"
)


def tenant_isolation_sql(table: str) -> str:
    """Idempotent DDL adding ``tenant_id`` and the RLS policy to ``table``.

    Existing rows become the default tenant's, so upgrading keeps single-tenant
    data visible.
    """
    return f"""
    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
    CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id);
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS {POLICY_NAME} ON {table};
    CREATE POLICY {POLICY_NAME} ON {table}
        USING {_SCOPE_PREDICATE}
        WITH CHECK {_SCOPE_PREDICATE};
    """


_SET_TENANT = "SELECT set_config('app.tenant_id', $1, false)"

# Raw connections whose session is known to be at the default tenant: the last
# session-level value sagaz gave them was 'default' (and nothing else sets it).
_at_default: WeakSet[Any] = WeakSet()


def _raw_connection(conn: Any) -> Any:
    # A pool hands out a proxy; its reset callback receives the connection.
    return getattr(conn, "_con", None) or conn


async def reset_to_default_tenant(conn: Any) -> None:
    """Pool ``reset`` callback: asyncpg's reset plus the default tenant, in one round trip."""
    await conn.execute(
        conn.get_reset_query() + "SELECT set_config('app.tenant_id', 'default', false);"
    )
    _at_default.add(conn)


#: Extra ``asyncpg.create_pool`` arguments for pools sagaz creates.
POOL_OPTIONS: dict[str, Any] = {"reset": reset_to_default_tenant}


async def apply_scope(conn: Any) -> None:
    """Set ``app.tenant_id`` on ``conn`` to the current scope (skipped when already default)."""
    tenant = current_tenant_id()
    raw = _raw_connection(conn)
    if tenant == DEFAULT_TENANT and raw in _at_default:
        return
    await conn.execute(_SET_TENANT, tenant)
    if tenant == DEFAULT_TENANT:
        _at_default.add(raw)
    else:
        _at_default.discard(raw)


@asynccontextmanager
async def acquire_scoped(pool: Any) -> AsyncIterator[Any]:
    """``pool.acquire()`` with ``app.tenant_id`` set for the current scope."""
    async with pool.acquire() as conn:
        await apply_scope(conn)
        yield conn
