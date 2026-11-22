"""Running a saga as a tenant (ADR-020)."""

from __future__ import annotations

import warnings
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from sagaz.core.tenant._context import TenantContext
from sagaz.core.tenant._errors import CrossTenantAccessError
from sagaz.core.tenant._quotas import quota_enforcer
from sagaz.core.tenant._scope import _enter_tenant, _exit_tenant

if TYPE_CHECKING:
    from sagaz.core.tenant._registry import TenantRegistry


def tenant_argument(
    where: str, tenant: TenantContext | str | None, **old: TenantContext | str | None
) -> TenantContext | str | None:
    """The tenant given as ``tenant=``, or under its pre-2.6.0 keyword (#572).

    Every entry point that runs work as a tenant takes ``tenant=``. Its former name
    (``tenant_context=`` or ``tenant_id=``) still works until 3.0, with a
    ``DeprecationWarning``; giving both is an error.
    """
    given = {name: value for name, value in old.items() if value is not None}
    if not given:
        return tenant
    (name, value), *_ = given.items()
    if tenant is not None:
        msg = f"{where}: pass the tenant once, as tenant= (not also {name}=)"
        raise TypeError(msg)
    warnings.warn(
        f"{where}({name}=...) is deprecated and will be removed in 3.0: use tenant=",
        DeprecationWarning,
        stacklevel=3,
    )
    return value


def resolve_tenant(
    tenant: TenantContext | str, registry: TenantRegistry | None = None
) -> TenantContext:
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


class _TenantExecution:
    """``async with``: a quota slot and the tenant scope, around one saga run.

    A plain class rather than nested generator-based context managers: it runs
    once per tenant saga, and the generator machinery cost more than the
    bookkeeping itself (see ``docs/benchmarks/tenancy-overhead.md``).
    """

    __slots__ = ("_tenant", "_tokens")

    def __init__(self, tenant: TenantContext) -> None:
        self._tenant = tenant

    async def __aenter__(self) -> TenantContext:
        quota_enforcer.acquire(self._tenant)
        try:
            self._tokens = _enter_tenant(self._tenant)
        except BaseException:
            quota_enforcer.release(self._tenant.tenant_id)
            raise
        return self._tenant

    async def __aexit__(self, *exc_info: object) -> None:
        _exit_tenant(self._tokens)
        quota_enforcer.release(self._tenant.tenant_id)


def tenant_execution(tenant: TenantContext) -> AbstractAsyncContextManager[TenantContext]:
    """Admit one saga of ``tenant`` against its quotas and run it in its scope."""
    return _TenantExecution(tenant)


def ensure_tenant_context_matches(context: dict[str, Any], tenant_id: str) -> None:
    """Reject an initial context that already claims a different tenant."""
    claimed = context.get("tenant_id")
    if claimed is not None and claimed != tenant_id:
        raise CrossTenantAccessError(str(claimed), tenant_id)
