"""The benchmarked saga and one measured run of it in a given mode."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from benchmarks.tenancy.stats import RunResult
from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.tenant import (
    DEFAULT_TENANT,
    TenantContext,
    TenantQuotas,
    TenantRegistry,
    tenant_scope,
)

SAGA_NAME = "bench_tenancy_order"


@dataclass(frozen=True)
class Mode:
    """How the sagas of a run are submitted, and which PostgreSQL isolation is on.

    Attributes:
        name: Label in reports.
        tenancy: Run each worker's sagas as its tenant (``tenant_context=``);
            otherwise every saga runs in the default tenant.
        registry: Resolve tenant ids through a ``TenantRegistry`` instead of
            passing ``TenantContext`` objects.
        rls: PostgreSQL only; ``False`` disables row-level security on the saga
            tables for the run (ablation).
        scope_sql: PostgreSQL only; ``False`` skips the ``set_config`` sagaz runs
            on each acquired connection (ablation, valid only without RLS).
    """

    name: str
    tenancy: bool
    registry: bool = False
    rls: bool = True
    scope_sql: bool = True

    @property
    def is_ablation(self) -> bool:
        return not (self.rls and self.scope_sql)


BASELINE = Mode("baseline", tenancy=False)
MULTI = Mode("multi", tenancy=True)
MULTI_REGISTRY = Mode("multi-registry", tenancy=True, registry=True)
BASELINE_RLS_OFF = Mode("baseline-rls-off", tenancy=False, rls=False)
MULTI_RLS_OFF = Mode("multi-rls-off", tenancy=True, rls=False)
BASELINE_NO_TENANT_SQL = Mode("baseline-no-tenant-sql", tenancy=False, rls=False, scope_sql=False)

STANDARD_MODES = (BASELINE, MULTI, MULTI_REGISTRY)
POSTGRES_ABLATIONS = (BASELINE_RLS_OFF, MULTI_RLS_OFF, BASELINE_NO_TENANT_SQL)

#: (mode, reference) pairs reported as overheads, when both modes ran.
COMPARISONS = (
    ("multi", "baseline"),
    ("multi-registry", "baseline"),
    ("multi", "multi-rls-off"),
    ("baseline", "baseline-rls-off"),
    ("baseline-rls-off", "baseline-no-tenant-sql"),
    ("multi", "baseline-no-tenant-sql"),
)


@dataclass(frozen=True)
class Plan:
    """The workload: ``tenants * sagas_per_tenant`` concurrent workers.

    Each worker runs ``sagas_per_worker`` sagas one after another, so a run
    completes ``tenants * sagas_per_tenant * sagas_per_worker`` sagas in every
    mode; only whether they carry a tenant differs.
    """

    tenants: int
    sagas_per_tenant: int
    sagas_per_worker: int = 1
    step_sleep_ms: float = 0.0

    def __post_init__(self) -> None:
        for name in ("tenants", "sagas_per_tenant", "sagas_per_worker"):
            if getattr(self, name) < 1:
                msg = f"{name} must be >= 1"
                raise ValueError(msg)
        if self.step_sleep_ms < 0:
            msg = "step_sleep_ms must be >= 0"
            raise ValueError(msg)

    @property
    def total_sagas(self) -> int:
        return self.tenants * self.sagas_per_tenant * self.sagas_per_worker

    def tenant_ids(self) -> list[str]:
        width = len(str(self.tenants))
        return [f"tenant-{i:0{width}d}" for i in range(self.tenants)]


class BenchOrderSaga(Saga):
    """Four steps, two of them compensatable; state persisted at start and end."""

    saga_name = SAGA_NAME
    step_sleep = 0.0

    async def _work(self) -> None:
        if self.step_sleep:
            await asyncio.sleep(self.step_sleep)

    @action("reserve")
    async def reserve(self, ctx: dict[str, Any]) -> dict[str, Any]:
        await self._work()
        return {"reservation": f"r-{ctx['saga_id']}"}

    @compensate("reserve")
    async def release(self, ctx: dict[str, Any]) -> None:
        await self._work()

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx: dict[str, Any]) -> dict[str, Any]:
        await self._work()
        return {"charged": ctx["amount"]}

    @compensate("charge")
    async def refund(self, ctx: dict[str, Any]) -> None:
        await self._work()

    @action("ship", depends_on=["charge"])
    async def ship(self, ctx: dict[str, Any]) -> dict[str, Any]:
        await self._work()
        return {"shipment": f"s-{ctx['saga_id']}"}

    @action("notify", depends_on=["ship"])
    async def notify(self, ctx: dict[str, Any]) -> dict[str, Any]:
        await self._work()
        return {"notified": True}


class PersistenceFailures(logging.Handler):
    """Counts the warnings sagaz logs when it fails to persist saga state.

    Saga execution logs and swallows storage errors, so a misconfigured backend
    (for example RLS rejecting writes) would otherwise look fast, not broken.
    """

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.count = 0
        self.last = ""

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "Failed to persist" in message:
            self.count += 1
            self.last = message


@contextmanager
def watch_persistence() -> Iterator[PersistenceFailures]:
    handler = PersistenceFailures()
    logger = logging.getLogger("sagaz")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


class RunFailedError(RuntimeError):
    """A run had failed sagas or unpersisted state, so its timing is meaningless."""


def tenant_args(plan: Plan, mode: Mode) -> tuple[list[Any], TenantRegistry | None]:
    """The ``tenant_context`` argument of each tenant, and the registry if any."""
    if not mode.tenancy:
        return [None] * plan.tenants, None
    quotas = TenantQuotas(
        max_concurrent_sagas=plan.sagas_per_tenant,  # exactly the load: checked, never hit
        max_step_duration_seconds=60.0,
        max_retries=3,
    )
    contexts = [TenantContext(tid, plan="bench", quotas=quotas) for tid in plan.tenant_ids()]
    if not mode.registry:
        return contexts, None
    registry = TenantRegistry()
    for context in contexts:
        registry.register(context)
    return [context.tenant_id for context in contexts], registry


async def run_once(storage: Any, plan: Plan, mode: Mode, round_: int, label: str) -> RunResult:
    """Run every saga of ``plan`` in ``mode`` and time it; raise if any saga failed."""
    tenants, registry = tenant_args(plan, mode)
    config = SagaConfig(
        storage=storage, metrics=False, logging=False, tracing=False, tenant_registry=registry
    )
    latencies: list[float] = []
    first_ids: list[tuple[str | None, str]] = []

    async def worker(tenant: Any, tenant_index: int, slot: int) -> None:
        for i in range(plan.sagas_per_worker):
            saga = BenchOrderSaga(config=config)
            saga.step_sleep = plan.step_sleep_ms / 1000
            saga_id = f"{label}-{tenant_index}-{slot}-{i}"
            started = time.perf_counter()
            await saga.run({"amount": 10}, saga_id, tenant_context=tenant)
            latencies.append(time.perf_counter() - started)
            if slot == 0 and i == 0:
                first_ids.append((_tenant_id(tenant), saga_id))

    workers = [
        worker(tenant, index, slot)
        for slot in range(plan.sagas_per_tenant)
        for index, tenant in enumerate(tenants)
    ]
    with watch_persistence() as failures:
        started = time.perf_counter()
        outcomes = await asyncio.gather(*workers, return_exceptions=True)
        wall = time.perf_counter() - started
    errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    if errors or failures.count:
        first = repr(errors[0]) if errors else "-"
        msg = (
            f"{mode.name} run {label}: {len(errors)} failed workers (first: {first}), "
            f"{failures.count} persistence failures (last: {failures.last or '-'})"
        )
        raise RunFailedError(msg)
    await verify_persisted(storage, first_ids[:5])
    return RunResult.from_latencies(mode.name, round_, latencies, wall)


def _tenant_id(tenant: Any) -> str | None:
    if tenant is None:
        return None
    return tenant.tenant_id if isinstance(tenant, TenantContext) else str(tenant)


async def verify_persisted(storage: Any, samples: list[tuple[str | None, str]]) -> None:
    """Check sampled sagas are stored as completed in their tenant only."""
    for tenant_id, saga_id in samples:
        with tenant_scope(tenant_id or DEFAULT_TENANT):
            state = await storage.load_saga_state(saga_id)
        if not state or state["status"] != "completed":
            msg = f"saga {saga_id} of tenant {tenant_id or DEFAULT_TENANT} not stored as completed"
            raise RunFailedError(msg)
        if tenant_id is not None and await storage.load_saga_state(saga_id) is not None:
            msg = f"saga {saga_id} of tenant {tenant_id} is visible to the default tenant"
            raise RunFailedError(msg)
