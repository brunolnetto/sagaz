"""Tenant scoping shared by the storage backends (ADR-020).

Backends never take a tenant parameter: they read the current scope from
:mod:`sagaz.core.tenant`. Records written outside a tenant scope belong to
``"default"``; :func:`sagaz.core.tenant.system_scope` reads across tenants.
"""

from __future__ import annotations

from sagaz.core.tenant import DEFAULT_TENANT, current_tenant_id, is_system_scope

#: Column / field that stores a record's tenant.
TENANT_FIELD = "tenant_id"

#: Prefix of every Redis key that belongs to a non-default tenant.
REDIS_TENANT_NAMESPACE = "sagaz"


def scoped_tenant() -> str | None:
    """The tenant reads and writes are restricted to, or ``None`` in the system scope."""
    return None if is_system_scope() else current_tenant_id()


def write_tenant(record_tenant: str | None = None) -> str:
    """The tenant a new record belongs to.

    In a tenant scope it is always that tenant (a conflicting ``record_tenant``
    is rejected). In the system scope the record must name its own tenant,
    falling back to ``"default"``.
    """
    from sagaz.core.tenant import ensure_tenant_access

    if is_system_scope():
        return record_tenant or DEFAULT_TENANT
    if record_tenant is not None:
        ensure_tenant_access(record_tenant)
    return current_tenant_id()


def redis_tenant_prefix(base_prefix: str, tenant_id: str) -> str:
    """Key prefix for ``tenant_id``.

    The default tenant keeps the historical keys, so existing single-tenant
    data stays readable; every other tenant lives under
    ``sagaz:{tenant_id}:{base_prefix}``.
    """
    if tenant_id == DEFAULT_TENANT:
        return base_prefix
    return f"{REDIS_TENANT_NAMESPACE}:{tenant_id}:{base_prefix}"
