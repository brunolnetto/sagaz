"""
Chaos Engineering for saga resilience testing.

Implements ADR-017: Chaos Engineering Automation

Provides ChaosMonkey for systematic fault injection during saga testing,
inspired by Netflix Chaos Monkey and the Gremlin platform.

Usage::

    from sagaz.testing import ChaosMonkey

    chaos = ChaosMonkey(
        failure_rate=0.1,           # 10% of steps fail
        timeout_probability=0.05,   # 5% of steps timeout
        latency_range=(100, 500),   # 100-500 ms delay injected
        target_steps=["charge"],    # Only these steps get chaos
        seed=42,                    # Reproducible experiments
    )

    result = await chaos.intercept_step("charge", action_fn, ctx)
    report = chaos.report()
"""

from __future__ import annotations

import asyncio
import random as _random_module
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FaultType(StrEnum):
    """Types of faults that ChaosMonkey can inject."""

    FAILURE = "failure"
    TIMEOUT = "timeout"
    LATENCY = "latency"


@dataclass
class ChaosReport:
    """
    Summary of a chaos experiment.

    Attributes:
        total_injections: Total number of faults injected.
        by_type: Count of injections broken down by FaultType.
        recoveries: Count of faults that the saga recovered from.
    """

    total_injections: int
    by_type: dict[FaultType, int]
    recoveries: dict[FaultType, int]

    def __str__(self) -> str:
        return (
            f"ChaosReport(total={self.total_injections}, "
            f"by_type={self.by_type}, recoveries={self.recoveries})"
        )

    def __repr__(self) -> str:
        return self.__str__()


class ChaosMonkey:
    """
    Systematic fault injector for saga step testing.

    Parameters
    ----------
    failure_rate:
        Probability [0, 1] that a step raises an exception.
    timeout_probability:
        Probability [0, 1] that a step raises ``asyncio.TimeoutError``.
    latency_range:
        ``(min_ms, max_ms)`` delay injected before each step runs.
        ``None`` disables latency injection.
    target_steps:
        Restrict chaos to these step names only.
        Empty list means *all* steps are targeted.
    exception_types:
        Pool of exception classes chosen randomly when a failure is injected.
        Defaults to ``[RuntimeError]``.
    seed:
        Optional integer seed for reproducible experiments.
    """

    def __init__(
        self,
        failure_rate: float = 0.0,
        timeout_probability: float = 0.0,
        latency_range: tuple[int, int] | None = None,
        target_steps: list[str] | None = None,
        exception_types: list[type[Exception]] | None = None,
        seed: int | None = None,
    ) -> None:
        self.failure_rate = failure_rate
        self.timeout_probability = timeout_probability
        self.latency_range = latency_range
        self.target_steps: list[str] = target_steps or []
        self.exception_types: list[type[Exception]] = exception_types or [RuntimeError]
        self.random = _random_module.Random(seed)
        self.injections: dict[FaultType, int] = defaultdict(int)
        self.recoveries: dict[FaultType, int] = defaultdict(int)

    # ── public API ─────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Return True if any chaos is configured."""
        return bool(
            self.failure_rate > 0 or self.timeout_probability > 0 or self.latency_range is not None
        )

    async def intercept_step(
        self,
        step_name: str,
        action: Callable[..., Any],
        ctx: Any,
    ) -> Any:
        """
        Intercept a saga step and potentially inject a fault.

        Parameters
        ----------
        step_name:
            Name of the saga step being executed.
        action:
            The async callable that performs the real step work.
        ctx:
            Saga context dict passed to the action.

        Returns
        -------
        Any
            The return value of *action* when no fault is injected.

        Raises
        ------
        RuntimeError (or chosen exception type):
            When a failure is injected.
        asyncio.TimeoutError:
            When a timeout is injected.
        """
        if not self._is_targeted(step_name):
            return await action(ctx)

        # 1 - Latency injection (runs before every targeted step)
        if self.latency_range is not None:
            delay_ms = self.random.uniform(self.latency_range[0], self.latency_range[1])
            await asyncio.sleep(delay_ms / 1000)
            self.injections[FaultType.LATENCY] += 1

        # 2 - Timeout injection (takes precedence over random failure)
        if self.random.random() < self.timeout_probability:
            self.injections[FaultType.TIMEOUT] += 1
            msg = f"Chaos: injected timeout in '{step_name}'"
            raise asyncio.TimeoutError(msg)

        # 3 - Random failure injection
        if self.random.random() < self.failure_rate:
            self.injections[FaultType.FAILURE] += 1
            exc_class = self.random.choice(self.exception_types)
            msg = f"Chaos: injected failure in '{step_name}'"
            raise exc_class(msg)

        return await action(ctx)

    def report(self) -> ChaosReport:
        """Return a snapshot of chaos experiment metrics."""
        return ChaosReport(
            total_injections=sum(self.injections.values()),
            by_type=dict(self.injections),
            recoveries=dict(self.recoveries),
        )

    def reset(self) -> None:
        """Reset injection counters; preserve configuration."""
        self.injections = defaultdict(int)
        self.recoveries = defaultdict(int)

    # ── internal ───────────────────────────────────────────────────────────

    def _is_targeted(self, step_name: str) -> bool:
        """Return True if this step should receive chaos injection."""
        if not self.target_steps:
            return True  # all steps targeted when list is empty
        return step_name in self.target_steps


class ChaosDisabled:
    """
    No-op chaos implementation.

    Use as a sentinel when you want the chaos parameter to be optional::

        async def run_saga(saga, ctx, chaos=ChaosDisabled()):
            result = await chaos.intercept_step("step", action, ctx)
    """

    @property
    def is_active(self) -> bool:
        return False

    async def intercept_step(
        self,
        step_name: str,
        action: Callable[..., Any],
        ctx: Any,
    ) -> Any:
        """Execute action directly, without any fault injection."""
        return await action(ctx)

    def report(self) -> ChaosReport:
        """Return an empty report."""
        return ChaosReport(total_injections=0, by_type={}, recoveries={})

    def reset(self) -> None:
        """No-op."""
