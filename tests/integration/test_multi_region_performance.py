"""Single-region sagas pay (almost) nothing for multi-region support (#59).

What multi-region support adds to a saga whose steps declare no region is one
check per run (``_check_regions``) and one indirection per step
(``_run_step``). This measures that added work directly, with many iterations,
and compares it with the time of a whole 3-step run. Comparing two noisy saga
timings instead would measure the machine, not the code. Run with
``-m performance``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from sagaz import Saga, action
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._execution import ExecutionEngine

pytestmark = [pytest.mark.performance]

ITERATIONS, RUNS, ROUNDS = 50_000, 500, 9


class Local(Saga):
    saga_name = "local"

    @action("a")
    async def a(self, ctx):
        return {"a": 1}

    @action("b", depends_on=["a"])
    async def b(self, ctx):
        return {"b": 2}

    @action("c", depends_on=["b"])
    async def c(self, ctx):
        return {"c": 3}


async def _best_us(fn, iterations: int) -> float:
    """Fastest of ROUNDS timings of *iterations* awaits of *fn*, per call."""
    best = float("inf")
    for _ in range(ROUNDS):
        started = time.perf_counter()
        for _ in range(iterations):
            await fn()
        best = min(best, (time.perf_counter() - started) / iterations * 1e6)
    return best


def test_region_none_overhead_is_under_one_percent():
    saga = Local(config=SagaConfig(metrics=False, logging=False))
    engine = ExecutionEngine(saga)
    saga._context = {}
    step = saga.get_step("a")

    async def check():
        engine._check_regions()

    async def direct():
        await step.forward_fn(saga._context)

    async def routed():
        await engine._run_step(step)

    async def run():
        await saga.run({})

    async def measure() -> tuple[float, float, float, float]:
        return (
            await _best_us(check, ITERATIONS),
            await _best_us(direct, ITERATIONS),
            await _best_us(routed, ITERATIONS),
            await _best_us(run, RUNS),
        )

    check_us, direct_us, routed_us, run_us = asyncio.run(measure())
    added = check_us + 3 * max(routed_us - direct_us, 0.0)
    print(
        f"\nadded per run: {added:.2f} µs (check {check_us:.2f}, "
        f"per step {routed_us - direct_us:.2f}) of {run_us:.1f} µs ({added / run_us:.2%})"
    )
    assert added / run_us < 0.01
