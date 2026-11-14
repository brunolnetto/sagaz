"""
Tenant isolation for ``PostgreSQLOutboxStorage`` (ADR-020).

Two layers protect each tenant's outbox rows:

* Row-level security: ``saga_outbox``, ``saga_outbox_archive`` and
  ``consumer_inbox`` get a ``tenant_id`` column and the policy from
  :func:`~sagaz.core.storage.backends.postgresql._tenancy.tenant_isolation_sql`,
  and every connection is scoped with ``app.tenant_id``.
* Explicit filters: outside the system scope, every query also carries
  :func:`tenant_predicate`, so isolation holds for superusers and
  ``BYPASSRLS`` roles, which RLS does not restrict.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sagaz.core.storage._tenancy import scoped_tenant
from sagaz.core.storage.backends.postgresql._tenancy import (
    acquire_scoped,
    apply_scope,
    tenant_isolation_sql,
)
from sagaz.core.storage.interfaces.outbox import OutboxStorageError

#: Tables of the outbox schema that hold tenant-owned rows.
TENANT_TABLES = ("saga_outbox", "saga_outbox_archive", "consumer_inbox")

#: Idempotent DDL adding ``tenant_id`` and RLS to every outbox table. Rows that
#: predate multi-tenancy become the default tenant's.
OUTBOX_TENANCY_SCHEMA = "\n".join(tenant_isolation_sql(table) for table in TENANT_TABLES)


def tenant_predicate(index: int) -> str:
    """SQL restricting rows to the tenant bound as parameter ``$index``.

    Bind :func:`tenant_param` there: ``NULL`` (the system scope) matches every row.
    """
    return f"(${index}::text IS NULL OR tenant_id = ${index})"


def tenant_param() -> str | None:
    """The tenant queries are restricted to, ``None`` in the system scope."""
    return scoped_tenant()


@asynccontextmanager
async def scoped_connection(pool: Any, connection: Any | None = None) -> AsyncIterator[Any]:
    """Yield ``connection`` (scoped to the current tenant) or one acquired from ``pool``.

    A caller-supplied connection keeps the ``app.tenant_id`` set here after the
    call, like any session setting; every acquire from the storage's own pool
    sets it again.
    """
    if connection is not None:
        await apply_scope(connection)
        yield connection
        return
    if not pool:
        msg = "Storage not initialized. Call initialize() first."
        raise OutboxStorageError(msg)
    async with acquire_scoped(pool) as conn:
        yield conn
