"""Multi-tenancy overhead on each storage backend (ADR-020, #54).

Runs a small configuration of ``benchmarks/tenancy`` (20 tenants x 5
concurrent sagas, 7 interleaved rounds) and checks that running the same sagas
as many tenants is not grossly slower than running them in the default tenant.

The bound, ``MAX_OVERHEAD_PCT``, is deliberately loose: on a shared laptop a
single pair of back-to-back runs can differ by +-40% with no code change, so
only the median over rounds is checked, and only against regressions an order
of magnitude above the <5% target (an extra query per step, a pool per tenant).
The documented numbers come from the full benchmark; see
``docs/benchmarks/tenancy-overhead.md``.

Kept out of the unit suite by the ``integration`` marker (CI's unit job runs
``-m "not integration"``). Run with::

    pytest tests/integration/test_tenancy_overhead.py -m performance -v -s
"""

from __future__ import annotations

import pytest

from benchmarks.tenancy import backends, report, runner, workload

pytestmark = [pytest.mark.integration, pytest.mark.performance, pytest.mark.slow]

MAX_OVERHEAD_PCT = 50.0
PLAN = workload.Plan(tenants=20, sagas_per_tenant=5)
ROUNDS = 7


async def _measure(name: str, options: backends.BackendOptions) -> report.BackendResult:
    async with backends.open_backend(name, options) as session:
        result = await runner.measure(
            session, PLAN, [workload.BASELINE, workload.MULTI], ROUNDS, warmup=1
        )
    print("\n" + report.results_table([result]))
    return result


def _overhead(result: report.BackendResult) -> float:
    (overhead,) = result.overheads
    return overhead.median_pct


@pytest.mark.parametrize("name", ["memory", "sqlite"])
async def test_overhead_without_containers(name):
    assert _overhead(await _measure(name, backends.BackendOptions())) < MAX_OVERHEAD_PCT


async def test_overhead_on_postgresql_with_row_level_security(app_role_url):
    options = backends.BackendOptions(postgres_url=app_role_url, postgres_pool_size=10)
    result = await _measure("postgres", options)
    assert result.info["rls_enforced"]
    # Exact and load-independent: running as a tenant sends no extra statement.
    counts = result.info["statements_per_saga"]
    assert counts["multi"] == counts["baseline"]
    assert _overhead(result) < MAX_OVERHEAD_PCT


async def test_overhead_on_redis(redis_url):
    options = backends.BackendOptions(redis_url=redis_url)
    assert _overhead(await _measure("redis", options)) < MAX_OVERHEAD_PCT
