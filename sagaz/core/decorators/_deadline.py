"""A deadline for a whole orchestrated saga (#568).

Steps have timeouts; a deadline bounds the saga's forward execution, all its steps
together. ``await saga.run(ctx, deadline=30)`` (seconds, or a ``timedelta``), or a
``deadline`` attribute on the saga class as its default.

When the deadline passes, the steps still running are cancelled and the saga fails as
when a step fails: it compensates the steps that completed and raises
``SagaFailedError``, caused by a ``SagaTimeoutError``. The deadline does not bound the
compensation, which runs to its end under its own timeouts, so that a saga is never left
half undone. A cancelled step did not complete, so it is not compensated.

Choreography has the same notion: ``begin(deadline=)``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sagaz.core.exceptions import SagaDefinitionError, SagaTimeoutError

Deadline = timedelta | float | int | None


def deadline_seconds(deadline: object) -> float | None:
    """*deadline* (seconds or a ``timedelta``) in seconds; ``None`` for no deadline."""
    if deadline is None:
        return None
    if isinstance(deadline, timedelta):
        deadline = deadline.total_seconds()
    if isinstance(deadline, bool) or not isinstance(deadline, int | float) or deadline <= 0:
        msg = f"deadline must be a positive number of seconds or a timedelta, not {deadline!r}"
        raise SagaDefinitionError(msg)
    return float(deadline)


async def within(seconds: float | None, saga_name: str, run: Callable[[], Awaitable[None]]) -> None:
    """Await ``run()``; past *seconds*, cancel it and raise ``SagaTimeoutError``."""
    if seconds is None:
        await run()
        return
    timer = asyncio.timeout(seconds)
    try:
        async with timer:
            await run()
    except TimeoutError as error:
        if not timer.expired():  # a step's own timeout, not the saga's deadline
            raise
        msg = f"saga '{saga_name}' did not finish within its deadline of {seconds:g}s"
        raise SagaTimeoutError(msg) from error
