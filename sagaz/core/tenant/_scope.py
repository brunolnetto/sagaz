"""The tenant the current code runs as (ADR-020).

Storage backends read :func:`current_tenant_id` instead of taking a tenant
parameter, so their signatures stay unchanged. The value lives in a
:class:`contextvars.ContextVar`, so concurrent asyncio tasks each keep their own
tenant, and code that never sets one runs as :data:`DEFAULT_TENANT`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sagaz.core.tenant._context import (
    DEFAULT_TENANT,
    SYSTEM_TENANT,
    TenantContext,
    validate_tenant_id,
)
from sagaz.core.tenant._errors import CrossTenantAccessError

_current_tenant: ContextVar[str] = ContextVar("sagaz_tenant_id", default=DEFAULT_TENANT)
_current_context: ContextVar[TenantContext | None] = ContextVar(
    "sagaz_tenant_context", default=None
)


def current_tenant_id() -> str:
    """The tenant of the current scope (``"default"`` when none is set)."""
    return _current_tenant.get()


def current_tenant_context() -> TenantContext | None:
    """The full :class:`TenantContext` of the current scope, if one was given."""
    return _current_context.get()


def is_system_scope() -> bool:
    """True inside :func:`system_scope`, where storage spans every tenant."""
    return _current_tenant.get() == SYSTEM_TENANT


@contextmanager
def tenant_scope(tenant: str | TenantContext) -> Iterator[str]:
    """Run the enclosed code as ``tenant``; storage is scoped to it.

    Usable with ``with`` in sync and async code. Scopes nest, and the previous
    tenant is restored on exit, even on error.
    """
    context = tenant if isinstance(tenant, TenantContext) else None
    tenant_id = validate_tenant_id(context.tenant_id if context else tenant)
    tenant_token = _current_tenant.set(tenant_id)
    context_token = _current_context.set(context)
    try:
        yield tenant_id
    finally:
        _current_context.reset(context_token)
        _current_tenant.reset(tenant_token)


@contextmanager
def system_scope() -> Iterator[None]:
    """Run the enclosed code across all tenants.

    Meant for infrastructure such as the outbox worker, migrations and
    analytics. Writes made here must carry their own tenant id.
    """
    tenant_token = _current_tenant.set(SYSTEM_TENANT)
    context_token = _current_context.set(None)
    try:
        yield
    finally:
        _current_context.reset(context_token)
        _current_tenant.reset(tenant_token)


def ensure_tenant_access(record_tenant: str | None) -> None:
    """Raise :class:`CrossTenantAccessError` if a record is outside the current scope.

    Records without a tenant belong to :data:`DEFAULT_TENANT`. The system scope
    may access every record.
    """
    current = _current_tenant.get()
    owner = record_tenant or DEFAULT_TENANT
    if current != SYSTEM_TENANT and owner != current:
        raise CrossTenantAccessError(owner, current)
