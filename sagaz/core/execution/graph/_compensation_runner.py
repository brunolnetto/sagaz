"""Compensation execution mixin for ``SagaExecutionGraph`` (levels, retries, skips)."""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from sagaz.core.execution.graph._exceptions import CircularDependencyError
from sagaz.core.execution.graph._tracker import _CompensationTracker
from sagaz.core.execution.graph._types import (
    CompensationFailureStrategy,
    CompensationNode,
    CompensationResult,
    SagaCompensationContext,
)
from sagaz.core.execution.graph._utils import _detect_compensation_signature


class _GraphCompensationMixin:
    """Mixin executing registered compensations level by level."""

    # Attributes provided by the concrete graph host.
    nodes: dict[str, CompensationNode]
    _compensation_results: dict[str, Any]

    if TYPE_CHECKING:
        # Methods provided by ``_GraphOrderingMixin`` on the concrete graph host.
        def get_compensation_order(self) -> list[list[str]]: ...

        def _build_reverse_dependencies(self, steps: list[str]) -> dict[str, set[str]]: ...

    async def execute_compensations(
        self,
        context: dict[str, Any] | SagaCompensationContext,
        failure_strategy: CompensationFailureStrategy = CompensationFailureStrategy.CONTINUE_ON_ERROR,
        saga_id: str | None = None,
    ) -> CompensationResult:
        """
        Execute all compensations respecting dependencies and failure strategy.

        Args:
            context: Saga context (dict) or SagaCompensationContext
            failure_strategy: How to handle compensation failures
            saga_id: Saga ID (used when context is dict, ignored if SagaCompensationContext)

        Returns:
            CompensationResult with detailed execution info
        """
        start_time = time.time()
        comp_context = self._ensure_compensation_context(context, saga_id)

        # Get compensation order
        try:
            levels = self.get_compensation_order()
        except CircularDependencyError as e:
            return self._create_failure_result(e, start_time)

        # Execute all levels
        tracker = _CompensationTracker()
        await self._execute_all_levels(levels, comp_context, failure_strategy, tracker)

        return CompensationResult(
            success=len(tracker.failed) == 0,
            executed=tracker.executed,
            failed=tracker.failed,
            skipped=tracker.skipped,
            results=self._compensation_results.copy(),
            errors=tracker.errors,
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    def _ensure_compensation_context(
        self, context: dict[str, Any] | SagaCompensationContext, saga_id: str | None
    ) -> SagaCompensationContext:
        """Convert dict to SagaCompensationContext if needed."""
        if isinstance(context, dict):
            return SagaCompensationContext(
                saga_id=saga_id or "unknown",
                step_id="",
                original_context=context,
                compensation_results=self._compensation_results.copy(),
            )
        return context

    def _create_failure_result(self, error: Exception, start_time: float) -> CompensationResult:
        """Create a failed CompensationResult for structural errors."""
        return CompensationResult(
            success=False,
            executed=[],
            failed=[],
            skipped=[],
            results={},
            errors={"_graph": error},
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    async def _execute_all_levels(
        self,
        levels: list[list[str]],
        comp_context: SagaCompensationContext,
        failure_strategy: CompensationFailureStrategy,
        tracker: "_CompensationTracker",
    ) -> None:
        """Execute compensation levels, updating tracker with results."""
        for level in levels:
            if tracker.should_stop:
                tracker.skipped.extend(level)
                continue

            steps_to_execute, level_skipped = self._filter_level_steps(
                level, tracker.failed_set, failure_strategy
            )
            tracker.skipped.extend(level_skipped)

            level_results = await self._execute_level(
                steps_to_execute, comp_context, failure_strategy
            )

            self._process_level_results(level_results, comp_context, failure_strategy, tracker)

    def _filter_level_steps(
        self,
        level: list[str],
        failed_set: set[str],
        failure_strategy: CompensationFailureStrategy,
    ) -> tuple[list[str], list[str]]:
        """Filter steps in a level, returning (to_execute, skipped)."""
        to_execute = []
        skipped = []
        for step_id in level:
            if self._should_skip_step(step_id, failed_set, failure_strategy):
                skipped.append(step_id)
            else:
                to_execute.append(step_id)
        return to_execute, skipped

    def _process_level_results(
        self,
        level_results: dict[str, Any | Exception],
        comp_context: SagaCompensationContext,
        failure_strategy: CompensationFailureStrategy,
        tracker: "_CompensationTracker",
    ) -> None:
        """Process results from a level execution, updating tracker."""
        for step_id, result in level_results.items():
            if isinstance(result, Exception):
                tracker.failed.append(step_id)
                tracker.errors[step_id] = result
                tracker.failed_set.add(step_id)
                if failure_strategy == CompensationFailureStrategy.FAIL_FAST:
                    tracker.should_stop = True
            else:
                tracker.executed.append(step_id)
                if result is not None:
                    self._compensation_results[step_id] = result
                    comp_context.set_result(step_id, result)

    async def _execute_level(
        self,
        step_ids: list[str],
        comp_context: SagaCompensationContext,
        failure_strategy: CompensationFailureStrategy,
    ) -> dict[str, Any | Exception]:
        """
        Execute a level of compensations in parallel.

        Args:
            step_ids: List of step IDs to execute in parallel
            comp_context: Compensation context with original saga context and results
            failure_strategy: How to handle failures

        Returns:
            Dictionary mapping step_id to result or exception
        """
        if not step_ids:
            return {}

        # Create tasks for all steps in the level
        tasks = {
            step_id: self._execute_single_compensation(step_id, comp_context, failure_strategy)
            for step_id in step_ids
        }

        # Execute in parallel and gather results
        keys = list(tasks.keys())
        coroutines = list(tasks.values())

        # Use return_exceptions=True to allow some to fail without cancelling others
        executed_results = await asyncio.gather(*coroutines, return_exceptions=True)

        results = {}
        for step_id, result in zip(keys, executed_results, strict=False):
            results[step_id] = result
            # Store result immediately so subsequent levels accessing context can see it
            if result is not None and not isinstance(result, Exception):
                self._compensation_results[step_id] = result
                comp_context.set_result(step_id, result)

        return results

    async def _execute_single_compensation(
        self,
        step_id: str,
        comp_context: SagaCompensationContext,
        failure_strategy: CompensationFailureStrategy,
    ) -> Any:
        """
        Execute a single compensation with retry logic.

        Args:
            step_id: Step identifier
            comp_context: Compensation context with original saga context and results
            failure_strategy: How to handle failures

        Returns:
            Compensation result value (if any)

        Raises:
            Exception: If compensation fails after retries
        """
        node = self.nodes.get(step_id)
        if not node:
            return None

        # Update context with current step
        comp_context.step_id = step_id

        # Determine number of retries
        max_retries = (
            node.max_retries
            if failure_strategy == CompensationFailureStrategy.RETRY_THEN_CONTINUE
            else 0
        )

        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                # Detect function signature
                accepts_results = _detect_compensation_signature(node.compensation_fn)

                # Call compensation with appropriate signature
                if accepts_results:
                    result = await asyncio.wait_for(
                        node.compensation_fn(
                            comp_context.original_context, comp_context.compensation_results
                        ),
                        timeout=node.timeout_seconds,
                    )
                else:
                    # Context-only signature
                    result = await asyncio.wait_for(
                        node.compensation_fn(comp_context.original_context),
                        timeout=node.timeout_seconds,
                    )

                return result

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    # Exponential backoff before retry
                    await asyncio.sleep(2**attempt * 0.1)
                    continue
                # No more retries, raise the error
                raise

        # Should not reach here, but satisfy type checker
        if last_error:  # pragma: no cover
            raise last_error  # pragma: no cover
        return None  # pragma: no cover

    def _should_skip_step(
        self,
        step_id: str,
        failed_steps: set[str],
        failure_strategy: CompensationFailureStrategy,
    ) -> bool:
        """
        Determine if a step should be skipped based on failed dependencies.

        Args:
            step_id: Step to check
            failed_steps: Set of steps that have failed
            failure_strategy: The failure handling strategy

        Returns:
            True if step should be skipped, False otherwise
        """
        if failure_strategy != CompensationFailureStrategy.SKIP_DEPENDENTS:
            return False

        node = self.nodes.get(step_id)
        if not node:
            return False

        # Build compensation dependencies for this step
        # A step's compensation depends on the compensations of steps that depend on it
        # in forward execution (because those must compensate first)
        comp_deps = self._build_reverse_dependencies(list(self.nodes.keys()))

        # Check if any of the steps that must compensate before this one have failed
        steps_before_this = comp_deps.get(step_id, set())
        return any(dep in failed_steps for dep in steps_before_this)
