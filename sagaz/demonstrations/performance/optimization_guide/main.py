#!/usr/bin/env python3
"""
Optimization Guide — measure, compare, then tune saga performance

Three measured experiments, each comparing a baseline with an optimization:

  1. Sequential steps vs a parallel DAG       (independent I/O-bound steps)
  2. Storage backend latency                  (in-memory vs SQLite vs Redis*)
  3. Retry backoff tuning                     (conservative vs aggressive base)

Step work is simulated with short sleeps and every backend runs in-process
(*Redis is the in-memory backend plus a simulated network round trip), so
no infrastructure is needed and the whole guide finishes in well under a
second. Absolute numbers depend on the machine; the ratios are the point.

Usage:
    sagaz demo run optimization_guide
    python -m sagaz.demonstrations.performance.optimization_guide.main
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from sagaz.core.saga import Saga
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.core.types import SagaStatus

STEP_IO_SECONDS = 0.015
INDEPENDENT_STEPS = (
    "check_fraud",
    "reserve_stock",
    "quote_shipping",
    "load_profile",
    "apply_coupon",
    "estimate_tax",
)
STORAGE_OPERATIONS = 10
SIMULATED_RTT_SECONDS = 0.0005
MIN_SPEEDUP = 1.5


@dataclass(frozen=True)
class Comparison:
    """A baseline and an optimized variant of the same workload, in milliseconds."""

    experiment: str
    baseline: str
    baseline_ms: float
    optimized: str
    optimized_ms: float
    all_completed: bool = True

    @property
    def speedup(self) -> float:
        return self.baseline_ms / self.optimized_ms if self.optimized_ms else float("inf")


async def _timed(work: Callable[[], Awaitable[Any]]) -> tuple[float, Any]:
    """Run ``work`` and return (elapsed milliseconds, its result)."""
    start = time.perf_counter()
    result = await work()
    return (time.perf_counter() - start) * 1000, result


# --------------------------------------------------------------------------- 1


async def _validate(ctx: Any) -> dict[str, bool]:
    return {"valid": True}


async def _io_step(ctx: Any) -> dict[str, bool]:
    await asyncio.sleep(STEP_IO_SECONDS)  # stands in for a network call
    return {"ok": True}


async def _run_checkout(*, parallel: bool) -> SagaStatus:
    saga = Saga("Checkout")
    await saga.add_step("validate_order", _validate)
    for name in INDEPENDENT_STEPS:
        # dependencies=None chains each step after the previous one. Depending only
        # on validate_order lets the I/O steps fan out concurrently; a saga must stay
        # connected, so the fan-out hangs off that shared root step.
        await saga.add_step(name, _io_step, dependencies={"validate_order"} if parallel else None)
    return (await saga.execute()).status


async def parallelism_experiment() -> Comparison:
    sequential_ms, sequential = await _timed(lambda: _run_checkout(parallel=False))
    parallel_ms, parallel = await _timed(lambda: _run_checkout(parallel=True))
    return Comparison(
        "independent steps",
        "sequential",
        sequential_ms,
        "parallel DAG",
        parallel_ms,
        all_completed=sequential == parallel == SagaStatus.COMPLETED,
    )


# --------------------------------------------------------------------------- 2


class SimulatedRedisSagaStorage(InMemorySagaStorage):
    """In-memory storage that pays a fixed network round trip per call."""

    async def save_saga_state(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(SIMULATED_RTT_SECONDS)
        await super().save_saga_state(*args, **kwargs)

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        await asyncio.sleep(SIMULATED_RTT_SECONDS)
        return await super().load_saga_state(saga_id)


async def _save_and_load(storage: Any) -> None:
    for i in range(STORAGE_OPERATIONS):
        saga_id = f"saga-{i}"
        await storage.save_saga_state(
            saga_id, "Checkout", SagaStatus.COMPLETED, [], {"order_id": i}
        )
        await storage.load_saga_state(saga_id)


async def storage_experiment() -> dict[str, float]:
    """Milliseconds for ``STORAGE_OPERATIONS`` save+load pairs on each backend."""
    sqlite = SQLiteSagaStorage(":memory:")
    try:
        backends: dict[str, Any] = {
            "in-memory": InMemorySagaStorage(),
            "sqlite": sqlite,
            "redis (simulated RTT)": SimulatedRedisSagaStorage(),
        }
        timings: dict[str, float] = {}
        for name, storage in backends.items():
            timings[name], _ = await _timed(partial(_save_and_load, storage))
        return timings
    finally:
        await sqlite.close()


# --------------------------------------------------------------------------- 3


def _flaky(failures: int) -> Callable[[Any], Awaitable[dict[str, int]]]:
    """A step that fails ``failures`` times before succeeding (a transient outage)."""
    calls = {"n": 0}

    async def step(ctx: Any) -> dict[str, int]:
        calls["n"] += 1
        if calls["n"] <= failures:
            msg = "upstream temporarily unavailable"
            raise ConnectionError(msg)
        return {"attempts": calls["n"]}

    return step


async def _run_with_backoff(base: float) -> SagaStatus:
    saga = Saga("Checkout", retry_backoff_base=base)
    await saga.add_step("call_payment_gateway", _flaky(failures=2), max_retries=3)
    return (await saga.execute()).status


async def backoff_experiment() -> Comparison:
    conservative_ms, conservative = await _timed(lambda: _run_with_backoff(0.02))
    aggressive_ms, aggressive = await _timed(lambda: _run_with_backoff(0.002))
    return Comparison(
        "retry backoff (2 transient failures)",
        "base=20ms",
        conservative_ms,
        "base=2ms",
        aggressive_ms,
        all_completed=conservative == aggressive == SagaStatus.COMPLETED,
    )


# ----------------------------------------------------------------------- guide


def verify(parallelism: Comparison, storage: dict[str, float], backoff: Comparison) -> list[str]:
    """Return expectations the measurements violated (empty when all hold)."""
    problems = [
        f"a saga in '{c.experiment}' did not complete"
        for c in (parallelism, backoff)
        if not c.all_completed
    ]
    # Thresholds sit well below the expected ratios (~4-6x) so a loaded machine
    # does not turn timing noise into a false alarm.
    if parallelism.speedup < MIN_SPEEDUP:
        problems.append(f"parallel DAG was not at least {MIN_SPEEDUP}x faster than sequential")
    if storage["in-memory"] >= storage["redis (simulated RTT)"]:
        problems.append("in-memory storage was not faster than a networked backend")
    if backoff.speedup < MIN_SPEEDUP:
        problems.append(f"aggressive backoff did not recover at least {MIN_SPEEDUP}x sooner")
    return problems


def _print_comparison(c: Comparison) -> None:
    print(f"  ▶ {c.experiment}")
    print(f"      {c.baseline:<22} {c.baseline_ms:7.1f} ms")
    print(f"      {c.optimized:<22} {c.optimized_ms:7.1f} ms   ({c.speedup:.1f}x faster)")


async def _run() -> None:
    # Phase 1: Setup
    print(
        f"🏎  Optimization guide — {len(INDEPENDENT_STEPS)} steps of "
        f"{STEP_IO_SECONDS * 1000:.0f} ms I/O, {STORAGE_OPERATIONS} storage round trips\n"
    )

    # Phase 2: Execute
    parallelism = await parallelism_experiment()
    storage = await storage_experiment()
    backoff = await backoff_experiment()

    _print_comparison(parallelism)
    print("  ▶ storage backend (save + load)")
    for backend, ms in storage.items():
        print(f"      {backend:<22} {ms:7.1f} ms")
    _print_comparison(backoff)

    # Phase 3: Verify
    problems = verify(parallelism, storage, backoff)
    print()
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        msg = "measurements did not support the recommendations"
        raise RuntimeError(msg)
    print("✅ Recommendations hold on this machine:")
    print("   • let independent steps depend only on what they need, so they fan out")
    print("   • keep hot-path state in fast storage; budget for network round trips")
    print("   • size retry_backoff_base to how quickly the dependency recovers")


if __name__ == "__main__":
    asyncio.run(_run())
