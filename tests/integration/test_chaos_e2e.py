"""End-to-end chaos tests: real ``Saga`` execution through ``ChaosMonkey`` (ADR-017).

Each step action is wrapped with :meth:`ChaosMonkey.intercept_step`, so faults are
injected inside the real executor and must trigger real compensation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from sagaz.core.saga import Saga
from sagaz.core.types import SagaStatus
from sagaz.testing import ChaosMonkey, FaultType

pytestmark = pytest.mark.integration

StepFn = Callable[[Any], Awaitable[Any]]


class _Ledger:
    """Records which actions and compensations actually ran."""

    def __init__(self) -> None:
        self.actions: list[str] = []
        self.compensations: list[str] = []

    def action(self, name: str) -> StepFn:
        async def run(ctx: Any) -> dict[str, str]:
            self.actions.append(name)
            return {name: "done"}

        return run

    def compensation(self, name: str) -> Callable[[Any, Any], Awaitable[None]]:
        # Compensations receive (step_result, context).
        async def undo(result: Any, ctx: Any) -> None:
            self.compensations.append(name)

        return undo


def _chaotic(monkey: ChaosMonkey, name: str, action: StepFn) -> StepFn:
    async def wrapped(ctx: Any) -> Any:
        return await monkey.intercept_step(name, action, ctx)

    return wrapped


async def _three_step_saga(
    monkey: ChaosMonkey, ledger: _Ledger, *, step_timeout: float = 5.0
) -> Saga:
    saga = Saga("ChaosE2E", retry_backoff_base=0.001)
    for name in ("step_1", "step_2", "step_3"):
        await saga.add_step(
            name,
            _chaotic(monkey, name, ledger.action(name)),
            ledger.compensation(name),
            timeout=step_timeout,
            max_retries=0,
        )
    return saga


@pytest.mark.parametrize(
    ("chaos", "step_timeout", "fault"),
    [
        pytest.param({"failure_rate": 1.0}, 5.0, FaultType.FAILURE, id="injected-failure"),
        pytest.param({"timeout_probability": 1.0}, 5.0, FaultType.TIMEOUT, id="injected-timeout"),
        pytest.param(
            {"latency_range": (200, 250)}, 0.05, FaultType.LATENCY, id="latency-exceeds-timeout"
        ),
    ],
)
async def test_fault_in_step_2_compensates_step_1(chaos, step_timeout, fault):
    monkey = ChaosMonkey(target_steps=["step_2"], seed=7, **chaos)
    ledger = _Ledger()
    saga = await _three_step_saga(monkey, ledger, step_timeout=step_timeout)

    result = await saga.execute()

    assert result.success is False
    assert result.status == SagaStatus.ROLLED_BACK
    assert ledger.compensations == ["step_1"]
    assert "step_3" not in ledger.actions
    assert monkey.report().by_type[fault] >= 1


async def test_untargeted_steps_run_normally():
    monkey = ChaosMonkey(failure_rate=1.0, target_steps=["not_in_saga"])
    ledger = _Ledger()
    saga = await _three_step_saga(monkey, ledger)

    result = await saga.execute()

    assert result.success is True
    assert result.status == SagaStatus.COMPLETED
    assert ledger.actions == ["step_1", "step_2", "step_3"]
    assert ledger.compensations == []
    assert monkey.report().total_injections == 0


async def _failure_pattern(seed: int, runs: int = 12) -> list[bool]:
    monkey = ChaosMonkey(failure_rate=0.5, target_steps=["step_2"], seed=seed)
    outcomes = []
    for _ in range(runs):
        saga = await _three_step_saga(monkey, _Ledger())
        outcomes.append((await saga.execute()).success)
    return outcomes


async def test_same_seed_reproduces_the_same_failure_pattern():
    first = await _failure_pattern(seed=1234)
    second = await _failure_pattern(seed=1234)

    assert first == second
    assert True in first
    assert False in first  # the pattern actually mixes outcomes


async def test_different_seeds_change_the_pattern():
    assert await _failure_pattern(seed=1) != await _failure_pattern(seed=2)
