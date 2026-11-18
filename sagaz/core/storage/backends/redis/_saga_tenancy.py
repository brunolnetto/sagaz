"""Tenant key prefixes and system-scope fan-out for :class:`RedisSagaStorage` (ADR-020).

Every key of tenant ``T`` lives under ``redis_tenant_prefix(key_prefix, T)``:
the default tenant keeps the historical ``{key_prefix}...`` keys, other tenants
use ``sagaz:{T}:{key_prefix}...``. Two tenants may therefore use the same saga
id, each in its own keyspace (data hash and status/name indexes alike).

The system scope has no keyspace of its own: its operations run once per
tenant (each inside ``tenant_scope``). Tenants are discovered by scanning
``sagaz:*:{key_prefix}*``, which costs a pass over those keys.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from sagaz.core.storage._tenancy import (
    REDIS_TENANT_NAMESPACE,
    TENANT_FIELD,
    redis_tenant_prefix,
    write_tenant,
)
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope

T = TypeVar("T")


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class _RedisSagaTenancyMixin:
    """Per-tenant key prefixes and running an operation for every tenant."""

    key_prefix: str

    if TYPE_CHECKING:

        async def _get_redis(self) -> Any: ...

    def _tenant_prefix(self) -> str:
        """Key prefix of the tenant the current scope reads and writes."""
        return redis_tenant_prefix(self.key_prefix, write_tenant())

    def _foreign_tenant_key(self) -> re.Pattern[str]:
        """Matches keys of non-default tenants (in case they share the default prefix)."""
        return re.compile(
            rf"{REDIS_TENANT_NAMESPACE}:[a-z0-9][a-z0-9._-]*:{re.escape(self.key_prefix)}"
        )

    async def _all_tenants(self) -> list[str]:
        """Tenants with keys in this storage (the default tenant always included)."""
        redis_client = await self._get_redis()
        pattern = f"{REDIS_TENANT_NAMESPACE}:*:{self.key_prefix}*"
        tenants = {DEFAULT_TENANT}
        async for key in redis_client.scan_iter(match=pattern, count=1000):
            tenants.add(_decode(key).split(":", 2)[1])
        return sorted(tenants)

    async def _for_each_tenant(
        self, operation: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> list[tuple[str, T]]:
        """Run ``operation`` in every tenant's scope; return ``(tenant, result)`` pairs."""
        results: list[tuple[str, T]] = []
        for tenant in await self._all_tenants():
            with tenant_scope(tenant):
                results.append((tenant, await operation(*args, **kwargs)))
        return results

    @staticmethod
    def _with_tenant(saga_data: dict[str, Any]) -> dict[str, Any]:
        """Tag a record read in the current scope with its tenant (legacy records lack it)."""
        saga_data.setdefault(TENANT_FIELD, write_tenant())
        return saga_data
