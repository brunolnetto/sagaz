"""Tenant resolution for outbox events, shared by the outbox backends (ADR-020).

Which tenant an inserted event belongs to:

* In a tenant scope, the scope's tenant. An event whose ``tenant_id`` names a
  *different, non-default* tenant is rejected with
  :class:`~sagaz.core.tenant.CrossTenantAccessError`; ``"default"`` (the field's
  default value) counts as "not set" and is replaced by the scope's tenant.
* In the system scope (e.g. the outbox worker, data transfer), the event's own
  ``tenant_id``.
* Outside any scope, ``"default"`` (so an explicit other tenant is rejected).

Reads, updates and deletes made outside the system scope only see the current
tenant's events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.tenant import DEFAULT_TENANT, validate_tenant_id

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxEvent


def resolve_event_tenant(event: OutboxEvent) -> str:
    """Set and return the tenant ``event`` is written under (see module docstring)."""
    explicit = None if event.tenant_id == DEFAULT_TENANT else event.tenant_id
    tenant = validate_tenant_id(write_tenant(explicit))
    event.tenant_id = tenant
    return tenant


def event_visible(event: OutboxEvent) -> bool:
    """True if ``event`` belongs to the current scope (always in the system scope)."""
    scope = scoped_tenant()
    return scope is None or event.tenant_id == scope
