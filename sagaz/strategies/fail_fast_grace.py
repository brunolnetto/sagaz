"""
FAIL_FAST_WITH_GRACE Strategy Implementation

Balanced approach: cancel remaining steps but allow grace period for in-flight ones.
Provides good balance between resource efficiency and graceful handling.
"""

import asyncio
from typing import Any

from sagaz.strategies.base import ParallelExecutionStrategy


class FailFastWithGraceStrategy(ParallelExecutionStrategy):
    """
    Implements FAIL_FAST_WITH_GRACE parallel failure strategy

    When one parallel step fails:
    1. Cancel remaining parallel steps that haven't started yet
    2. Wait gracefully for in-flight parallel steps to complete (with timeout)
    3. Begin compensation after graceful completion or timeout
    """

    def __init__(self, grace_period: float = 2.0):
        """
        Initialize strategy with grace period

        Args:
            grace_period: Maximum time to wait for in-flight steps to complete
        """
        self.grace_period = grace_period

    async def execute_parallel_steps(self, steps: list[Any]) -> list[Any]:
        """
        Execute steps in parallel with graceful failure handling

        Args:
            steps: List of steps to execute (each step should have an execute() method)

        Returns:
            List of results from all successful steps

        Raises:
            Exception: First exception encountered from any step
        """
        if not steps:
            return []

        tasks = [asyncio.create_task(step.execute()) for step in steps]
        return await self._execute_and_handle_failures(tasks)

    async def _execute_and_handle_failures(self, tasks: list) -> list[Any]:
        """Execute tasks and handle any failures."""
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            return await self._process_completed_tasks(tasks, done, pending)
        except asyncio.CancelledError:
            self._cancel_all_tasks(tasks)
            raise

    async def _process_completed_tasks(self, tasks: list, done: set, pending: set) -> list[Any]:
        """Process completed tasks and handle failures."""
        failed_task = self._find_failed_task(done)
        if failed_task:
            await self._handle_failure_with_grace(pending)
            raise failed_task.exception()  # type: ignore[misc]
        return [task.result() for task in tasks]

    def _find_failed_task(self, done: set) -> asyncio.Task | None:
        """Find the first failed task in done set."""
        for task in done:
            if task.exception():
                return task  # type: ignore[no-any-return]
        return None

    async def _handle_failure_with_grace(self, pending: set):
        """Allow grace period for pending tasks, then cancel."""
        if not pending:
            return

        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=self.grace_period
            )
        except TimeoutError:  # pragma: no cover
            for task in pending:  # pragma: no cover
                if not task.done():  # pragma: no cover
                    task.cancel()  # pragma: no cover

    def _cancel_all_tasks(self, tasks: list):
        """Cancel all incomplete tasks."""
        for task in tasks:
            if not task.done():
                task.cancel()

    def should_wait_for_completion(self) -> bool:
        """FAIL_FAST_WITH_GRACE waits for in-flight tasks only"""
        return True

    def get_description(self) -> str:
        """Human-readable description of this strategy"""
        return "FAIL_FAST_WITH_GRACE: Cancel pending, wait for in-flight steps"
