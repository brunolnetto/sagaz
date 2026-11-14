"""Count the PostgreSQL statements (client round trips) each saga issues, per mode.

Unlike timings, the count is exact and unaffected by machine load: it shows
whether running as a tenant adds queries (it should not), and how many of a
saga's statements are the ``set_config`` sagaz runs on each acquired
connection (compare a mode with ``baseline-no-tenant-sql``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from benchmarks.tenancy.workload import BenchOrderSaga, Mode, Plan, tenant_args
from sagaz.core.config import SagaConfig

#: ``asyncpg.Connection`` methods that send a statement (``executemany`` sends
#: one batch; transactions issue BEGIN and COMMIT through ``execute``).
METHODS = ("execute", "executemany", "fetch", "fetchrow", "fetchval")


@contextmanager
def count_statements() -> Iterator[Counter[str]]:
    """Count statements sent through any asyncpg connection while active."""
    from asyncpg.connection import Connection

    counts: Counter[str] = Counter()
    originals = {name: getattr(Connection, name) for name in METHODS}

    def counting(name: str, method: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            counts[name] += 1
            return await method(self, *args, **kwargs)

        return wrapper

    for name, method in originals.items():
        setattr(Connection, name, counting(name, method))
    try:
        yield counts
    finally:
        for name, method in originals.items():
            setattr(Connection, name, method)


async def statements_per_saga(
    storage: Any,
    prepare: Callable[[Mode], Awaitable[None]],
    modes: Sequence[Mode],
    sagas: int = 20,
) -> dict[str, float]:
    """Statements per saga in each mode, from ``sagas`` sagas run one at a time."""
    plan = Plan(tenants=sagas, sagas_per_tenant=1)
    result = {}
    for mode in modes:
        await prepare(mode)
        tenants, registry = tenant_args(plan, mode)
        config = SagaConfig(
            storage=storage, metrics=False, logging=False, tracing=False, tenant_registry=registry
        )
        with count_statements() as counts:
            for i, tenant in enumerate(tenants):
                saga = BenchOrderSaga(config=config)
                await saga.run({"amount": 10}, f"count-{mode.name}-{i}", tenant_context=tenant)
        result[mode.name] = sum(counts.values()) / sagas
    return result
