"""Quota enforcement around saga execution (ADR-020)."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sagaz.core.tenant._context import TenantContext
from sagaz.core.tenant._errors import QuotaExceededError, TenantSuspendedError
from sagaz.core.tenant._scope import current_tenant_context


class QuotaEnforcer:
    """Admits tenant sagas and caps their step timeouts and retries.

    Concurrency is counted per process: limit sagas across several workers with
    a shared external limiter if you need a global bound.
    """

    def __init__(self) -> None:
        self._running: Counter[str] = Counter()

    def running(self, tenant_id: str) -> int:
        """Sagas of ``tenant_id`` currently admitted in this process."""
        return self._running[tenant_id]

    @asynccontextmanager
    async def admit(self, tenant: TenantContext) -> AsyncIterator[None]:
        """Hold a concurrency slot for ``tenant`` while one saga runs."""
        if not tenant.active:
            raise TenantSuspendedError(tenant.tenant_id)
        limit = tenant.quotas.max_concurrent_sagas
        current = self._running[tenant.tenant_id]
        if limit is not None and current >= limit:
            raise QuotaExceededError(tenant.tenant_id, "max_concurrent_sagas", limit, current + 1)
        self._running[tenant.tenant_id] += 1
        try:
            yield
        finally:
            self._running[tenant.tenant_id] -= 1
            if not self._running[tenant.tenant_id]:
                del self._running[tenant.tenant_id]


def capped_timeout(seconds: float) -> float:
    """``seconds``, lowered to the current tenant's ``max_step_duration_seconds``."""
    tenant = current_tenant_context()
    limit = tenant.quotas.max_step_duration_seconds if tenant else None
    return seconds if limit is None else min(seconds, limit)


def capped_retries(retries: int) -> int:
    """``retries``, lowered to the current tenant's ``max_retries``."""
    tenant = current_tenant_context()
    limit = tenant.quotas.max_retries if tenant else None
    return retries if limit is None else min(retries, limit)


#: Process-wide enforcer used by ``Saga.run(..., tenant_context=...)``.
quota_enforcer = QuotaEnforcer()
