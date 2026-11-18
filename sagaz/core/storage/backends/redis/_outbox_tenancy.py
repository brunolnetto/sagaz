"""
Per-tenant keys for ``RedisOutboxStorage`` (ADR-020).

Every key of a tenant lives under
:func:`~sagaz.core.storage._tenancy.redis_tenant_prefix`, so the default tenant
keeps the historical ``{prefix}:...`` keys and tenant ``acme`` uses
``sagaz:acme:{prefix}:...``. Operations made in a tenant scope only touch that
tenant's keys.

The system scope (the outbox worker) spans every tenant: the set
``{prefix}:tenants`` lists the non-default tenants that have outbox data, and
system-scope operations run once per listed tenant (plus the default one).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from sagaz.core.storage._tenancy import redis_tenant_prefix
from sagaz.core.storage.backends.redis._outbox_base import RedisOutboxMixinBase, logger
from sagaz.core.tenant import (
    DEFAULT_TENANT,
    current_tenant_id,
    is_system_scope,
    tenant_scope,
)

T = TypeVar("T")


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class RedisOutboxTenancyMixin(RedisOutboxMixinBase):
    """Tenant key naming, the tenant index and per-tenant fan-out."""

    _ready_groups: set[str]

    # ── key naming ──

    @property
    def _tenants_key(self) -> str:
        """Set of the non-default tenants that have outbox data."""
        return f"{self._prefix}:tenants"

    def _tenant_prefix(self, tenant_id: str | None = None) -> str:
        """Key prefix of ``tenant_id`` (default: the current tenant scope)."""
        tenant = tenant_id or current_tenant_id()
        if is_system_scope() and tenant_id is None:
            msg = "Redis outbox keys need a tenant: run this inside tenant_scope()"
            raise RuntimeError(msg)
        return redis_tenant_prefix(self._prefix, tenant)

    def _scoped_stream_key(self, tenant_id: str | None = None) -> str:
        return f"{self._tenant_prefix(tenant_id)}:events"

    def _scoped_processing_key(self) -> str:
        return f"{self._tenant_prefix()}:processing"

    def _scoped_dlq_key(self) -> str:
        return f"{self._tenant_prefix()}:dlq"

    def _meta_pattern(self, tenant_id: str | None = None) -> str:
        return f"{self._tenant_prefix(tenant_id)}:meta:*"

    # ── tenant index ──

    async def _known_tenants(self) -> list[str]:
        """The default tenant followed by every tenant with outbox data."""
        members = await self._redis.smembers(self._tenants_key)
        others = sorted({_text(member) for member in members or ()} - {DEFAULT_TENANT})
        return [DEFAULT_TENANT, *others]

    async def _scope_tenants(self) -> list[str]:
        """Tenants the current scope covers: all known ones in the system scope."""
        if is_system_scope():
            return await self._known_tenants()
        return [current_tenant_id()]

    async def _per_tenant(self, operation: Callable[[], Awaitable[T]]) -> list[T]:
        """Run ``operation`` once per tenant of the scope, inside that tenant's scope."""
        if not is_system_scope():
            return [await operation()]
        results = []
        for tenant in await self._known_tenants():
            with tenant_scope(tenant):
                results.append(await operation())
        return results

    async def _find_event_tenant(self, event_id: str, hint: str | None = None) -> str | None:
        """The tenant holding ``event_id``, checking ``hint`` first."""
        candidates = await self._known_tenants()
        if hint in candidates:
            candidates.remove(hint)
            candidates.insert(0, hint)
        for tenant in candidates:
            if await self._redis.exists(f"{self._tenant_prefix(tenant)}:meta:{event_id}"):
                return tenant
        return None

    @asynccontextmanager
    async def _event_tenant_scope(
        self, event_id: str, hint: str | None = None
    ) -> AsyncIterator[str | None]:
        """Scope the block to the tenant of ``event_id``.

        Outside the system scope that is the current tenant. In the system scope
        the event is looked up (``hint`` first); ``None`` means it does not exist.
        """
        if not is_system_scope():
            yield current_tenant_id()
            return
        tenant = await self._find_event_tenant(event_id, hint)
        if tenant is None:
            yield None
            return
        with tenant_scope(tenant):
            yield tenant

    # ── consumer groups ──

    async def _ensure_group(self, stream_key: str) -> None:
        """Create the consumer group of ``stream_key`` once per process."""
        if stream_key in self._ready_groups:
            return
        try:
            await self._redis.xgroup_create(stream_key, self._consumer_group, id="0", mkstream=True)
            logger.info(f"Created consumer group '{self._consumer_group}' on {stream_key}")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._ready_groups.add(stream_key)
