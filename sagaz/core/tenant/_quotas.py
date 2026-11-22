"""Quota enforcement around saga execution (ADR-020)."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
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
        # Tasks waiting for a slot of a tenant (acquire_waiting), woken on release.
        self._waiters: defaultdict[str, list[asyncio.Future[None]]] = defaultdict(list)

    def running(self, tenant_id: str) -> int:
        """Sagas of ``tenant_id`` currently admitted in this process."""
        return self._running[tenant_id]

    def acquire(self, tenant: TenantContext) -> None:
        """Take a concurrency slot for ``tenant``; pair with :meth:`release`."""
        if not tenant.active:
            raise TenantSuspendedError(tenant.tenant_id)
        limit = tenant.quotas.max_concurrent_sagas
        current = self._running[tenant.tenant_id]
        if limit is not None and current >= limit:
            raise QuotaExceededError(tenant.tenant_id, "max_concurrent_sagas", limit, current + 1)
        self._running[tenant.tenant_id] = current + 1

    async def acquire_waiting(self, tenant: TenantContext) -> None:
        """Like :meth:`acquire`, but wait for a free slot instead of raising.

        A suspended tenant still raises ``TenantSuspendedError``. Used by
        choreography (#564): a delivery over the quota waits, as backpressure.
        """
        while True:
            try:
                self.acquire(tenant)
            except QuotaExceededError:
                waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                self._waiters[tenant.tenant_id].append(waiter)
                try:
                    await waiter
                finally:
                    waiters = self._waiters.get(tenant.tenant_id, [])
                    if waiter in waiters:
                        waiters.remove(waiter)
            else:
                return

    def release(self, tenant_id: str) -> None:
        """Give back a slot taken by :meth:`acquire`, waking whoever waits for one."""
        remaining = self._running[tenant_id] - 1
        if remaining > 0:
            self._running[tenant_id] = remaining
        else:
            del self._running[tenant_id]
        for waiter in self._waiters.pop(tenant_id, []):
            if not waiter.done():
                waiter.set_result(None)

    @asynccontextmanager
    async def admit(self, tenant: TenantContext) -> AsyncIterator[None]:
        """Hold a concurrency slot for ``tenant`` while one saga runs."""
        self.acquire(tenant)
        try:
            yield
        finally:
            self.release(tenant.tenant_id)


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
