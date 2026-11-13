#!/usr/bin/env python3
"""
Chaos Patterns — inject faults into a real saga and watch it recover

Uses :class:`sagaz.testing.ChaosMonkey` to wrap step actions of an order
saga and runs three experiments:

  1. Random step failure     → the compensation chain undoes completed steps
  2. Timeout injection       → the step is retried, then the saga rolls back
  3. Parallel (DAG) failure  → completed branches are undone, the join never runs

Every fault is injected in-process (seeded, so runs are reproducible);
no external infrastructure is required.

Usage:
    sagaz demo run chaos_patterns
    python -m sagaz.demonstrations.reliability.chaos_patterns.main
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sagaz.core.saga import Saga
from sagaz.core.types import SagaStatus
from sagaz.testing import ChaosMonkey, FaultType

Action = Callable[[Any], Awaitable[Any]]
Compensation = Callable[[Any, Any], Awaitable[None]]


@dataclass
class ExperimentResult:
    """Outcome of one chaos experiment, used for the Verify phase."""

    name: str
    status: SagaStatus
    executed: list[str]
    compensated: list[str]
    injections: dict[FaultType, int]
    attempts: dict[str, int] = field(default_factory=dict)


class OrderSystem:
    """In-memory stand-in for the services an order saga touches."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.compensated: list[str] = []

    def action(self, name: str) -> Action:
        async def run(ctx: Any) -> dict[str, str]:
            self.executed.append(name)
            return {name: "ok"}

        return run

    def compensation(self, name: str) -> Compensation:
        async def undo(result: Any, ctx: Any) -> None:
            self.compensated.append(name)

        return undo


def _with_chaos(monkey: ChaosMonkey, name: str, action: Action) -> Action:
    """Route a step action through the chaos monkey."""

    async def wrapped(ctx: Any) -> Any:
        return await monkey.intercept_step(name, action, ctx)

    return wrapped


async def _build_saga(
    monkey: ChaosMonkey,
    system: OrderSystem,
    steps: Sequence[tuple[str, set[str] | None]],
    *,
    timeout: float = 1.0,
    max_retries: int = 0,
) -> Saga:
    saga = Saga("ChaosOrderSaga", retry_backoff_base=0.001)
    for name, dependencies in steps:
        await saga.add_step(
            name,
            _with_chaos(monkey, name, system.action(name)),
            system.compensation(name),
            timeout=timeout,
            max_retries=max_retries,
            dependencies=dependencies,
        )
    return saga


SEQUENTIAL = [("reserve_stock", None), ("charge_card", None), ("ship_order", None)]


async def random_failure_experiment() -> ExperimentResult:
    """A failure in ``charge_card`` must undo ``reserve_stock`` and skip shipping."""
    monkey = ChaosMonkey(failure_rate=1.0, target_steps=["charge_card"], seed=42)
    system = OrderSystem()
    result = await (await _build_saga(monkey, system, SEQUENTIAL)).execute()
    return ExperimentResult(
        "random failure", result.status, system.executed, system.compensated, monkey.injections
    )


async def timeout_experiment(max_retries: int = 2) -> ExperimentResult:
    """A step that always times out is retried ``max_retries`` times, then rolled back."""
    monkey = ChaosMonkey(timeout_probability=1.0, target_steps=["charge_card"], seed=42)
    system = OrderSystem()
    attempts = {"charge_card": 0}

    async def count_attempts(ctx: Any) -> Any:
        attempts["charge_card"] += 1
        return await monkey.intercept_step("charge_card", system.action("charge_card"), ctx)

    saga = Saga("ChaosOrderSaga", retry_backoff_base=0.001)
    await saga.add_step(
        "reserve_stock", system.action("reserve_stock"), system.compensation("reserve_stock")
    )
    await saga.add_step(
        "charge_card",
        count_attempts,
        system.compensation("charge_card"),
        max_retries=max_retries,
    )
    await saga.add_step("ship_order", system.action("ship_order"))
    result = await saga.execute()
    return ExperimentResult(
        "timeout + retry",
        result.status,
        system.executed,
        system.compensated,
        monkey.injections,
        attempts,
    )


async def parallel_failure_experiment() -> ExperimentResult:
    """Two parallel branches after validation; one fails.

    Everything that completed (validation and the healthy branch) is compensated,
    the failed branch has nothing to undo, and the join step never runs.
    """
    monkey = ChaosMonkey(failure_rate=1.0, target_steps=["charge_card"], seed=42)
    system = OrderSystem()
    dag = [
        ("validate_order", None),
        ("reserve_stock", {"validate_order"}),
        ("charge_card", {"validate_order"}),
        ("ship_order", {"reserve_stock", "charge_card"}),
    ]
    result = await (await _build_saga(monkey, system, dag)).execute()
    return ExperimentResult(
        "parallel DAG failure",
        result.status,
        system.executed,
        system.compensated,
        monkey.injections,
    )


def _report(result: ExperimentResult) -> None:
    faults = ", ".join(f"{k.value}={v}" for k, v in sorted(result.injections.items())) or "none"
    print(f"  ▶ {result.name}")
    print(f"      status       : {result.status.value}")
    print(f"      executed     : {result.executed or '∅'}")
    print(f"      compensated  : {result.compensated or '∅'}")
    print(f"      faults       : {faults}")
    if result.attempts:
        print(f"      attempts     : {result.attempts}")


def verify(results: list[ExperimentResult]) -> list[str]:
    """Return a list of violated expectations (empty when every experiment behaved)."""
    by_name = {r.name: r for r in results}
    problems: list[str] = []

    failure = by_name["random failure"]
    if failure.status != SagaStatus.ROLLED_BACK or failure.compensated != ["reserve_stock"]:
        problems.append("random failure did not roll back reserve_stock")
    if "ship_order" in failure.executed:
        problems.append("ship_order ran after charge_card failed")

    timeout = by_name["timeout + retry"]
    if timeout.attempts.get("charge_card", 0) < 2:
        problems.append("timed-out step was not retried")
    if timeout.status != SagaStatus.ROLLED_BACK:
        problems.append("timeout did not end in rollback")

    parallel = by_name["parallel DAG failure"]
    if "ship_order" in parallel.executed:
        problems.append("ship_order ran although a parent branch failed")
    if "charge_card" in parallel.compensated:
        problems.append("the failed branch was compensated")

    return problems


async def _run() -> None:
    # Phase 1: Setup
    print("⚡ Chaos patterns — ChaosMonkey wraps the steps of an order saga (seed=42)\n")

    # Phase 2: Execute
    results = [
        await random_failure_experiment(),
        await timeout_experiment(),
        await parallel_failure_experiment(),
    ]
    for result in results:
        _report(result)

    # Phase 3: Verify
    problems = verify(results)
    print()
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        msg = "chaos experiments did not behave as expected"
        raise RuntimeError(msg)
    print("✅ Every injected fault was contained by compensation")


if __name__ == "__main__":
    asyncio.run(_run())
