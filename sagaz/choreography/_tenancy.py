"""Tenancy for choreography: who may run, and how many at once (#564, ADR-020).

An orchestrated saga resolves its tenant through ``SagaConfig.tenant_registry``,
refuses a suspended one and takes a slot of its ``max_concurrent_sagas`` quota. A
choreography participant does the same for the tenant an event names:

- with a registry, an event's tenant must be registered and active. Otherwise the
  participant does not run its handler and asks for compensation, as a failed handler
  does. ``begin()`` raises instead, before publishing anything;
- a transaction takes one slot of its tenant's quota while this process handles any
  of its deliveries. Nested in-process handlers of one transaction share that slot, so
  they cannot deadlock. The slots are those of ``quota_enforcer``, shared with
  orchestrated sagas, so the quota covers both modes. Over the quota, ``begin()``
  raises ``QuotaExceededError`` and a delivery waits for a slot;
- handlers and compensations run in the tenant's scope with its ``TenantContext``, so
  its ``max_retries`` and ``max_step_duration_seconds`` cap theirs.

Without a registry, an event's tenant id runs with the default plan and no quotas, as
before.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sagaz.core.tenant import (
    InvalidTenantIdError,
    TenantContext,
    TenantNotFoundError,
    TenantSuspendedError,
    quota_enforcer,
    resolve_tenant,
)

if TYPE_CHECKING:
    from sagaz.core.tenant import QuotaEnforcer, TenantRegistry

#: The errors that make a participant refuse an event's tenant.
REFUSED = (TenantNotFoundError, TenantSuspendedError, InvalidTenantIdError)


class Tenancy:
    """A choreography engine's view of its tenants: registry, suspension and quotas.

    Args:
        registry: The ``TenantRegistry`` to resolve tenants with; default, the global
            configuration's ``tenant_registry`` (``SagaConfig``), read when needed.
        enforcer: The quota slots; default, the process-wide ``quota_enforcer``.
    """

    def __init__(
        self,
        registry: TenantRegistry | None = None,
        enforcer: QuotaEnforcer = quota_enforcer,
    ) -> None:
        self._registry = registry
        self._enforcer = enforcer
        # (tenant, correlation id) -> deliveries of it this process is handling.
        self._held: dict[tuple[str, str], int] = {}

    def registry(self) -> TenantRegistry | None:
        if self._registry is not None:
            return self._registry
        from sagaz.core.config import get_config

        registry: TenantRegistry | None = get_config().tenant_registry
        return registry

    def resolve(self, tenant: TenantContext | str) -> TenantContext:
        """*tenant*'s context (a given one is used as is, as ``resolve_tenant`` does);
        raises one of :data:`REFUSED` if it may not run."""
        tenant = resolve_tenant(tenant, self.registry())
        if not tenant.active:
            raise TenantSuspendedError(tenant.tenant_id)
        return tenant

    def context(self, tenant_id: str) -> TenantContext | str:
        """*tenant_id*'s context if it resolves, else the id: for compensations, which
        always run, even for a tenant suspended meanwhile."""
        try:
            return resolve_tenant(tenant_id, self.registry())
        except REFUSED:
            return tenant_id

    @asynccontextmanager
    async def transaction(
        self, tenant: TenantContext, correlation_id: str | None, *, wait: bool
    ) -> AsyncIterator[None]:
        """Hold a quota slot for *correlation_id* of *tenant* (shared while held).

        Over the quota it waits for a slot if *wait*, else raises
        ``QuotaExceededError``. An event without a correlation id is no transaction
        and takes no slot.
        """
        if not correlation_id:
            yield
            return
        key = (tenant.tenant_id, correlation_id)
        await self._enter(tenant, key, wait=wait)
        try:
            yield
        finally:
            self._exit(key)

    async def _enter(self, tenant: TenantContext, key: tuple[str, str], *, wait: bool) -> None:
        if key in self._held:
            self._held[key] += 1
            return
        if wait:
            await self._enforcer.acquire_waiting(tenant)
        else:
            self._enforcer.acquire(tenant)
        if key in self._held:  # another delivery of it took a slot while this one waited
            self._enforcer.release(tenant.tenant_id)
            self._held[key] += 1
            return
        self._held[key] = 1

    def _exit(self, key: tuple[str, str]) -> None:
        remaining = self._held[key] - 1
        if remaining:
            self._held[key] = remaining
            return
        del self._held[key]
        self._enforcer.release(key[0])
