"""
Tenant filtering for the ``SQLiteOutboxStorage`` queries (ADR-020).

Every query against ``outbox_events`` made outside the system scope is
restricted to the current tenant with :data:`TENANT_FILTER`, bound to
:func:`tenant_params`.
"""

from __future__ import annotations

from sagaz.core.storage._tenancy import scoped_tenant

#: ``WHERE`` predicate restricting rows to the current scope's tenant.
TENANT_FILTER = "(? IS NULL OR tenant_id = ?)"


def tenant_params() -> tuple[str | None, str | None]:
    """Parameters for :data:`TENANT_FILTER` (``None`` in the system scope)."""
    tenant = scoped_tenant()
    return (tenant, tenant)
