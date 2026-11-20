"""A background loop that stops between iterations, not in the middle of one.

Cancelling a task while it awaits a database call abandons the call, not the
work: the driver's thread (aiosqlite, for one) keeps waiting, for instance on
a lock, and reports its result later, possibly to an event loop that is gone
by then ("Event loop is closed"). :class:`Poller` signals its loop to stop and
waits for the iteration in progress; it cancels only an iteration that
overruns ``grace`` seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class Poller:
    """Runs ``step()`` every ``interval`` seconds in a task, until :meth:`stop`.

    Args:
        step: One iteration. Exceptions are logged, and the loop goes on.
        interval: Seconds between iterations (or a callable, read each time).
        grace: Seconds :meth:`stop` waits for the iteration in progress.
        name: For logs and the task's name.
    """

    def __init__(
        self,
        step: Callable[[], Awaitable[object]],
        interval: float | Callable[[], float],
        *,
        grace: float = 10.0,
        name: str = "poller",
    ) -> None:
        self._step = step
        self._interval = interval
        self.grace = grace
        self.name = name
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the loop (idempotent; needs a running event loop)."""
        if not self.running:
            self._stopping = asyncio.Event()
            self._task = asyncio.get_running_loop().create_task(self._run(), name=self.name)

    async def stop(self) -> None:
        """Stop after the iteration in progress (cancelled if it overruns ``grace``)."""
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), self.grace)
        except TimeoutError:
            logger.warning(
                "%s: iteration overran %.1fs on stop; cancelling it", self.name, self.grace
            )
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _seconds(self) -> float:
        return self._interval() if callable(self._interval) else self._interval

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._step()
            except Exception:
                logger.exception("%s: iteration failed", self.name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), self._seconds())
