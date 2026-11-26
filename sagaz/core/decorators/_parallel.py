"""What the steps of a parallel level do when one of them fails (#567).

``SagaConfig.failure_strategy`` chooses, for ``sagaz.Saga``:

- ``WAIT_ALL``: every step of the level runs to its end, then the saga compensates.
- ``FAIL_FAST``: the other steps still running are cancelled at once.
- ``FAIL_FAST_WITH_GRACE`` (the default): they get ``failure_grace_period`` seconds to
  finish, and those still running after it are cancelled.

Whatever the strategy, the saga then fails with the error of the first step of the level
(in declaration order) that failed, and compensates the steps that completed. A cancelled
step did not complete, so it is not compensated: if it can leave an external effect
half done, use ``WAIT_ALL``, or make the step safe to interrupt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from typing import Any

from sagaz.core.exceptions import SagaDefinitionError
from sagaz.core.types import ParallelFailureStrategy

DEFAULT_STRATEGY = ParallelFailureStrategy.FAIL_FAST_WITH_GRACE
DEFAULT_GRACE_PERIOD = 2.0


def grace_period(value: object) -> float:
    """*value* in seconds, or the default when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return DEFAULT_GRACE_PERIOD
    return float(value)


def failure_strategy(value: object) -> ParallelFailureStrategy:
    """*value* (a ``ParallelFailureStrategy``, its name or its value) as the enum.

    A string that names no strategy is a definition error. Anything else that is not a
    strategy (``None``, a stand-in configuration object's attribute) is the default.
    """
    if isinstance(value, ParallelFailureStrategy):
        return value
    if not isinstance(value, str):
        return DEFAULT_STRATEGY
    text = value.strip()
    for strategy in ParallelFailureStrategy:
        if text.upper() == strategy.name or text.lower() == strategy.value:
            return strategy
    names = ", ".join(strategy.name for strategy in ParallelFailureStrategy)
    msg = f"failure_strategy must be one of {names}, not {value!r}"
    raise SagaDefinitionError(msg)


async def run_level(
    steps: Sequence[Coroutine[Any, Any, None]],
    strategy: ParallelFailureStrategy,
    grace: float = DEFAULT_GRACE_PERIOD,
) -> None:
    """Run *steps* concurrently; if one fails, treat the others as *strategy* says.

    Raises the error of the first step, in the order given, that failed.
    """
    tasks = [asyncio.ensure_future(step) for step in steps]
    try:
        if strategy is ParallelFailureStrategy.WAIT_ALL:
            await asyncio.wait(tasks)
        else:
            _, running = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            if running and strategy is ParallelFailureStrategy.FAIL_FAST_WITH_GRACE:
                await asyncio.wait(running, timeout=grace)
    finally:  # a failure, the end of the grace period, or the saga itself being cancelled
        await _cancel(tasks)
    for task in tasks:
        if not task.cancelled() and (error := task.exception()) is not None:
            raise error


async def _cancel(tasks: Sequence[asyncio.Future[None]]) -> None:
    """Cancel the tasks still running and wait until they have stopped."""
    running = [task for task in tasks if not task.done()]
    for task in running:
        task.cancel()
    if running:
        await asyncio.wait(running)
