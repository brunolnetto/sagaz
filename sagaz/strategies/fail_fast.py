"""
FAIL_FAST Strategy Implementation

Cancels all other parallel steps immediately when one fails.
Most aggressive failure handling - minimizes resource usage and execution time.
"""

import asyncio
from typing import Any

from sagaz.strategies.base import ParallelExecutionStrategy


class FailFastStrategy(ParallelExecutionStrategy):
    """
    Implements FAIL_FAST parallel failure strategy
    
    When one parallel step fails:
    1. Immediately cancel all other parallel steps that haven't started
    2. Cancel running parallel steps (best effort)  
    3. Raise the first exception encountered
    """

    async def execute_parallel_steps(self, steps: list[Any]) -> list[Any]:
        """
        Execute steps in parallel, failing fast on first error
        
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
        """Execute tasks and handle failures."""
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            return await self._process_results(tasks, done, pending)
        except asyncio.CancelledError:
            self._cancel_all_tasks(tasks)
            raise

    async def _process_results(self, tasks: list, done: set, pending: set) -> list[Any]:
        """Process results, checking for failures."""
        failed_exception = await self._check_and_handle_failure(done, pending)
        if failed_exception:
            raise failed_exception
        return [task.result() for task in tasks]

    async def _check_and_handle_failure(self, done: set, pending: set):
        """Check for failed tasks. If found, cancel pending and return exception."""
        for task in done:
            if task.exception():
                await self._cancel_pending_tasks(pending)
                return task.exception()
        return None

    async def _cancel_pending_tasks(self, pending: set):
        """Cancel all pending tasks and wait briefly."""
        for pending_task in pending:
            pending_task.cancel()

        if pending:
            await asyncio.wait(pending, timeout=1.0)

    def _cancel_all_tasks(self, tasks: list):
        """Cancel all incomplete tasks."""
        for task in tasks:
            if not task.done():
                task.cancel()
