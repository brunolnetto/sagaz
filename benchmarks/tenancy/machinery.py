"""Direct timing of the per-saga work multi-tenancy adds in the client.

``Saga.run(..., tenant_context=...)`` does, on top of an untenanted run:
resolve the tenant (registry lookup or pass-through), check the initial
context, admit the saga against the tenant's quotas, enter the tenant scope
and copy the context with ``tenant_id``. Timing exactly that, in a tight loop,
gives a low-noise upper bound for the client-side overhead, which the
end-to-end runs (dominated by machine noise on a shared laptop) cannot
resolve below a few percent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sagaz.core.tenant import (
    TenantContext,
    TenantQuotas,
    TenantRegistry,
    ensure_tenant_context_matches,
    resolve_tenant,
    tenant_execution,
)


@dataclass(frozen=True)
class MachineryCost:
    """Microseconds per saga spent in the tenancy wrapper of ``Saga.run``."""

    context_us: float
    registry_us: float
    iterations: int


async def _loop(tenant: TenantContext | str, registry: TenantRegistry | None, n: int) -> float:
    initial = {"amount": 10}
    started = time.perf_counter()
    for _ in range(n):
        resolved = resolve_tenant(tenant, registry)
        ensure_tenant_context_matches(initial, resolved.tenant_id)
        async with tenant_execution(resolved):
            context = {**initial, "tenant_id": resolved.tenant_id}
    del context
    return time.perf_counter() - started


async def _empty_loop(n: int) -> float:
    started = time.perf_counter()
    for _ in range(n):
        pass
    return time.perf_counter() - started


async def measure_machinery(iterations: int = 50_000, repeats: int = 5) -> MachineryCost:
    """Best-of-``repeats`` cost of the tenancy wrapper (``TenantContext`` and registry id)."""
    tenant = TenantContext("tenant-0", quotas=TenantQuotas(max_concurrent_sagas=10))
    registry = TenantRegistry()
    registry.register(tenant)
    best_context = best_registry = float("inf")
    for _ in range(repeats):
        empty = await _empty_loop(iterations)
        best_context = min(best_context, await _loop(tenant, None, iterations) - empty)
        best_registry = min(best_registry, await _loop("tenant-0", registry, iterations) - empty)
    return MachineryCost(
        context_us=best_context / iterations * 1e6,
        registry_us=best_registry / iterations * 1e6,
        iterations=iterations,
    )
