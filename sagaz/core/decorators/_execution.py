"""Saga execution engine and compensation orchestration.

Handles running saga steps, managing lifecycle hooks, and executing
compensations on failure.
"""

import asyncio
import inspect
import uuid
from typing import TYPE_CHECKING, Any

from sagaz.core.logger import get_logger
from sagaz.core.types import SagaStatus

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga, SagaStepDefinition

logger = get_logger(__name__)


class ExecutionEngine:
    """Orchestrates saga execution and compensation."""

    def __init__(self, saga: "Saga"):
        """Initialize execution engine with saga instance.

        Args:
            saga: The Saga instance to execute
        """
        self.saga = saga

    async def run(
        self, initial_context: dict[str, Any], saga_id: str | None = None
    ) -> dict[str, Any]:
        """Execute this saga.

        Args:
            initial_context: Initial data for the saga
            saga_id: Optional saga identifier for tracing

        Returns:
            Final context with all step results merged

        Raises:
            Exception: If saga fails (compensations will be attempted first)
        """
        self._initialize_run(initial_context, saga_id)
        name = self._get_saga_name()
        self._register_compensations()

        # Persist start
        storage = self.saga._config.storage if self.saga._config else None
        if storage:
            try:
                await storage.save_saga_state(
                    self.saga._saga_id,
                    name,
                    SagaStatus.EXECUTING,
                    [],  # TODO: Track steps
                    self.saga._context,
                )
            except Exception as e:
                logger.warning(f"Failed to persist saga start: {e}")

        try:
            await self._notify_listeners(
                "on_saga_start", name, self.saga._saga_id, self.saga._context
            )
            await self._execute_all_levels()
            await self._notify_listeners(
                "on_saga_complete", name, self.saga._saga_id, self.saga._context
            )

            # Persist completion
            if storage:
                try:
                    await storage.save_saga_state(
                        self.saga._saga_id, name, SagaStatus.COMPLETED, [], self.saga._context
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist saga completion: {e}")

            return self.saga._context
        except Exception as e:
            await self._compensate()
            await self._notify_listeners(
                "on_saga_failed", name, self.saga._saga_id, self.saga._context, e
            )

            # Persist failure
            if storage:
                try:
                    await storage.save_saga_state(
                        self.saga._saga_id, name, SagaStatus.ROLLED_BACK, [], self.saga._context
                    )
                except Exception as e_storage:
                    logger.warning(f"Failed to persist saga failure: {e_storage}")

            raise

    def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None:
        """Initialize saga run state."""
        self.saga._saga_id = saga_id or initial_context.get("saga_id") or str(uuid.uuid4())
        self.saga._context = initial_context.copy()
        self.saga._context["saga_id"] = self.saga._saga_id
        self.saga._compensation_graph.reset_execution()

    def _register_compensations(self) -> None:
        """Register all compensations in the graph.

        Compensation dependencies are automatically derived from forward
        action dependencies. The compensation graph will auto-reverse them.
        """
        for step_def in self.saga._steps:
            if step_def.compensation_fn:
                self.saga._compensation_graph.register_compensation(
                    step_def.step_id,
                    step_def.compensation_fn,
                    depends_on=step_def.depends_on,  # Auto-reversed dependencies
                    compensation_type=step_def.compensation_type,
                    max_retries=step_def.max_retries,
                    timeout_seconds=step_def.compensation_timeout_seconds,
                )

    async def _execute_all_levels(self) -> None:
        """Execute steps level by level."""
        for level in self.saga.get_execution_order():
            await self._execute_level(level)

    def _get_saga_name(self) -> str:
        """Get the saga name from class attribute or class name."""
        return self.saga.saga_name or self.saga.__class__.__name__

    async def _notify_listeners(self, event_name: str, *args) -> None:
        """Notify all listeners of an event."""
        for listener in self.saga._instance_listeners:
            try:
                handler = getattr(listener, event_name, None)
                if handler:
                    result = handler(*args)
                    if inspect.iscoroutine(result):
                        await result
            except Exception as e:
                logger.warning(f"Listener {type(listener).__name__}.{event_name} error: {e}")

    async def _execute_level(self, level: list["SagaStepDefinition"]) -> None:
        """Execute all steps in a level concurrently."""
        if not level:
            return

        tasks = [self._execute_step(step) for step in level]

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for exceptions
        for result in results:
            if isinstance(result, Exception):
                raise result

    async def _execute_step(self, step: "SagaStepDefinition") -> None:
        """Execute a single step with lifecycle hooks and listeners."""
        saga_name = self._get_saga_name()

        # Notify listeners: step entering
        await self._notify_listeners("on_step_enter", saga_name, step.step_id, self.saga._context)

        # Call on_enter hook
        await self._call_hook(step.on_enter, self.saga._context, step.step_id)

        try:
            # Apply timeout
            result = await asyncio.wait_for(
                step.forward_fn(self.saga._context), timeout=step.timeout_seconds
            )

            # Merge result into context
            if result and isinstance(result, dict):
                self.saga._context.update(result)

            # Mark step as executed for compensation tracking
            self.saga._context[f"__{step.step_id}_completed"] = True
            self.saga._compensation_graph.mark_step_executed(step.step_id)

            # Handle pivot step completion - propagate taint to ancestors
            if step.pivot:
                self.saga._propagate_taint_from_pivot(step.step_id)
                logger.info(f"Pivot step '{step.step_id}' completed - ancestors are now tainted")

            # Call on_success hook
            await self._call_hook(step.on_success, self.saga._context, step.step_id, result)

            # Notify listeners: step success
            await self._notify_listeners(
                "on_step_success", saga_name, step.step_id, self.saga._context, result
            )

        except TimeoutError as e:
            # Call on_failure hook
            await self._call_hook(step.on_failure, self.saga._context, step.step_id, e)
            # Notify listeners: step failure
            await self._notify_listeners(
                "on_step_failure", saga_name, step.step_id, self.saga._context, e
            )
            msg = f"Step '{step.step_id}' timed out after {step.timeout_seconds}s"
            raise TimeoutError(msg)
        except Exception as e:
            # Call on_failure hook
            await self._call_hook(step.on_failure, self.saga._context, step.step_id, e)
            # Notify listeners: step failure
            await self._notify_listeners(
                "on_step_failure", saga_name, step.step_id, self.saga._context, e
            )
            raise

    async def _call_hook(self, hook: Any | None, *args) -> None:
        """Call a hook function, handling both sync and async hooks."""
        if hook is None:
            return

        try:
            result = hook(*args)
            # If it's a coroutine, await it
            if inspect.iscoroutine(result):
                await result
        except Exception as e:
            # Log but don't fail - hooks should not break saga execution
            logger.warning(f"Hook error (non-fatal): {e}")

    async def _compensate(self) -> None:
        """Execute compensations in dependency order, respecting pivot boundaries.

        v1.3.0: Compensation stops at pivot boundaries. Tainted steps (ancestors
        of completed pivots) are skipped, as are pivot steps themselves.
        """
        comp_levels = self.saga._compensation_graph.get_compensation_order()

        # Track how many steps we skip due to taint
        skipped_count = 0

        for level in comp_levels:
            # v1.3.0: Filter out tainted steps and pivot steps
            compensable_steps = []
            for step_id in level:
                if self.saga._is_step_tainted(step_id):
                    logger.info(f"Skipping compensation for tainted step: {step_id}")
                    skipped_count += 1
                    continue

                step = self.saga._step_registry.get(step_id)
                if step and step.pivot and step_id in self.saga._completed_pivots:
                    logger.info(f"Reached pivot boundary, stopping compensation: {step_id}")
                    skipped_count += 1
                    continue

                compensable_steps.append(step_id)

            if compensable_steps:
                tasks = [self._execute_compensation(step_id) for step_id in compensable_steps]
                # Execute compensations in parallel, don't fail on individual errors
                await asyncio.gather(*tasks, return_exceptions=True)

        if skipped_count > 0:
            logger.info(f"Pivot-aware compensation: skipped {skipped_count} tainted/pivot steps")

    async def _execute_compensation(self, step_id: str) -> None:
        """Execute a single compensation with lifecycle hook and listeners."""
        node = self.saga._compensation_graph.get_compensation_info(step_id)
        if not node:
            return

        # v1.3.0: Double-check taint status (in case it changed)
        if self.saga._is_step_tainted(step_id):
            logger.debug(f"Skipping compensation for tainted step: {step_id}")
            return

        saga_name = self._get_saga_name()

        # Get the on_compensate hook from the step definition
        step = self.saga._step_registry.get(step_id)
        on_compensate = step.on_compensate if step else None

        try:
            # Notify listeners: compensation starting
            await self._notify_listeners(
                "on_compensation_start", saga_name, step_id, self.saga._context
            )

            # Call on_compensate hook before compensation
            await self._call_hook(on_compensate, self.saga._context, step_id)

            await asyncio.wait_for(
                node.compensation_fn(self.saga._context), timeout=node.timeout_seconds
            )
            self.saga._context[f"__{step_id}_compensated"] = True

            # Notify listeners: compensation complete
            await self._notify_listeners(
                "on_compensation_complete", saga_name, step_id, self.saga._context
            )
        except Exception as e:
            # Log but don't fail - we want all compensations to attempt
            self.saga._context[f"__{step_id}_compensation_error"] = str(e)
