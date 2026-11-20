"""Internal step execution helpers for the saga engine.

This module contains implementation details of step execution that are
extracted from core/saga.py for maintainability. These are internal APIs
(prefixed with `_`) and should not be used directly by end users.
"""

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.core.context import SagaContext
    from sagaz.core.saga import SagaStep


class _StepExecutor:
    """Helper class to wrap SagaStep for strategy execution.

    Wraps a SagaStep and manages its execution, result storage, and
    compensation. This is an internal implementation detail.

    Attributes:
        step: The SagaStep to execute.
        saga_context: The saga execution context.
        result: Execution result (set after successful action).
        error: Exception raised during execution (if any).
        completed: Whether the step completed successfully.
    """

    def __init__(self, step: "SagaStep", saga_context: "SagaContext", saga: Any = None):
        """Initialize executor for a step and context.

        Args:
            step: The saga step to wrap and execute.
            saga_context: The saga execution context for the step.
        """
        self.step = step
        self.saga_context = saga_context
        self.result = None
        self.saga = saga  # for the phase 2 step chart's events (None: no events)
        self.error: Exception | None = None
        self.completed = False
        self.duration_ms = 0.0

    async def execute(self) -> Any:
        """Execute the step action and store result or error.

        Calls the step's action function, stores the result in both the
        step and the saga context for downstream steps, and marks as
        completed on success.

        Returns:
            The action result.

        Raises:
            Any exception raised by the step action.
        """
        started = time.monotonic()
        await self._event("start")
        try:
            result = await self.step.action(self.saga_context)
            self.duration_ms = (time.monotonic() - started) * 1000
            self.result = result
            self.step.result = result
            # Store result in context for dependent steps
            self.saga_context.set(self.step.name, result)
            self.completed = True
            await self._event("succeed")
            return result
        except Exception as e:
            self.error = e
            self.step.error = e
            await self._event("fail")
            raise

    async def _event(self, event: str) -> None:
        if self.saga is not None:
            await self.saga._step_event(self.step.name, event)

    async def compensate(self) -> None:
        """Execute the step compensation if available.

        If the step has a compensation function, calls it with the
        stored result (or None if execution never completed). Does
        nothing if no compensation function was provided.
        """
        if self.step.compensation:
            await self.step.compensation(self.result, self.saga_context)

    @property
    def name(self) -> str:
        """Return the step name.

        Returns:
            The name of the wrapped SagaStep.
        """
        return self.step.name
