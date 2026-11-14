"""Running a saga as a tenant (ADR-020)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sagaz.core.tenant._context import TenantContext
from sagaz.core.tenant._errors import CrossTenantAccessError
from sagaz.core.tenant._quotas import quota_enforcer
from sagaz.core.tenant._scope import tenant_scope


def resolve_tenant(tenant: TenantContext | str, registry: Any | None = None) -> TenantContext:
    """Turn a tenant id into its :class:`TenantContext`.

    With a registry, the id must be registered (its plan and quotas are used);
    without one, an id runs with default plan and no quotas.
    """
    if isinstance(tenant, TenantContext):
        return tenant
    if registry is not None:
        resolved: TenantContext = registry.get(tenant)
        return resolved
    return TenantContext(tenant)


@asynccontextmanager
async def tenant_execution(tenant: TenantContext) -> AsyncIterator[TenantContext]:
    """Admit one saga of ``tenant`` against its quotas and run it in its scope."""
    async with quota_enforcer.admit(tenant):
        with tenant_scope(tenant):
            yield tenant


def ensure_tenant_context_matches(context: dict[str, Any], tenant_id: str) -> None:
    """Reject an initial context that already claims a different tenant."""
    claimed = context.get("tenant_id")
    if claimed is not None and claimed != tenant_id:
        raise CrossTenantAccessError(str(claimed), tenant_id)
