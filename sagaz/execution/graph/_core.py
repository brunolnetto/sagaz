"""Core SagaExecutionGraph implementation."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sagaz.execution.graph._exceptions import CircularDependencyError, MissingDependencyError
from sagaz.execution.graph._tracker import _CompensationTracker
from sagaz.execution.graph._types import (
    CompensationFailureStrategy,
    CompensationNode,
    CompensationResult,
    CompensationType,
    SagaCompensationContext,
)
from sagaz.execution.graph._utils import _detect_compensation_signature


class SagaExecutionGraph:
    """
    Unified graph for managing both forward execution and compensation dependencies.

    This graph handles dependency ordering for both action execution (forward)
    and compensation (reversed). The same dependency structure is used in both
    directions - forward for execution, reversed for compensation.

    Key Features:
        - Parallel execution of independent steps/compensations
        - Dependency-based ordering (topological sort)
        - Supports different compensation types
        - Tracks executed steps for accurate compensation
        - Unified structure simplifies saga architecture

    Usage:
        >>> graph = SagaExecutionGraph()
        >>>
        >>> # Register steps with compensations and dependencies
        >>> graph.register_compensation("step1", undo_step1)
        >>> graph.register_compensation("step2", undo_step2, depends_on=["step1"])
        >>> graph.register_compensation("step3", undo_step3, depends_on=["step1", "step2"])
        >>>
        >>> # Mark steps as executed during saga execution
        >>> graph.mark_step_executed("step1")
        >>> graph.mark_step_executed("step2")
        >>>
        >>> # Get compensation order (automatically reversed from forward deps)
        >>> levels = graph.get_compensation_order()
        >>> # Returns: [["step2"], ["step1"]]
        >>> # step2 has dependency on step1 (forward), so step1 compensates AFTER step2
    """

    def __init__(self):
        """Initialise an empty execution graph with no registered compensations."""
        self.nodes: dict[str, CompensationNode] = {}
        self.executed_steps: list[str] = []
        self._compensation_results: dict[str, Any] = {}

    def register_compensation(
        self,
        step_id: str,
        compensation_fn: Callable[[dict[str, Any]], Awaitable[None]],
        depends_on: list[str] | None = None,
        compensation_type: CompensationType = CompensationType.MECHANICAL,
        description: str | None = None,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        """
        Register a compensation action for a step.

        Compensation functions can optionally return values and access results
        from previously executed compensations.

        Args:
            step_id: Unique identifier for this step
            compensation_fn: Async function to execute on compensation.
                Supports two signatures:
                - Context-only: async def fn(ctx) -> None
                - With results: async def fn(ctx, compensation_results) -> Any
            depends_on: Steps that must be compensated BEFORE this one
            compensation_type: Type of compensation action
            description: Optional description for logging
            max_retries: Max retry attempts (default: 3)
            timeout_seconds: Execution timeout (default: 30s)

        Example (context-only):
            >>> async def refund_payment(ctx):
            ...     await PaymentService.refund(ctx["charge_id"])
            >>>
            >>> graph.register_compensation(
            ...     "charge_payment",
            ...     refund_payment,
            ...     depends_on=["create_order"],
            ...     compensation_type=CompensationType.SEMANTIC,
            ...     description="Refund customer payment"
            ... )

        Example (with result passing):
            >>> async def cancel_order(ctx, comp_results=None):
            ...     cancellation = await OrderService.cancel(ctx["order_id"])
            ...     return {"cancellation_id": cancellation.id}
            >>>
            >>> async def refund_payment(ctx, comp_results=None):
            ...     cancel_id = comp_results.get("cancel_order", {}).get("cancellation_id")
            ...     await PaymentService.refund(ctx["charge_id"], ref=cancel_id)
            ...     return {"refund_id": "ref-123"}
        """
        node = CompensationNode(
            step_id=step_id,
            compensation_fn=compensation_fn,
            depends_on=depends_on or [],
            compensation_type=compensation_type,
            description=description or f"Compensate {step_id}",
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        self.nodes[step_id] = node

    def mark_step_executed(self, step_id: str) -> None:
        """
        Mark a step as successfully executed.

        Only executed steps will be compensated on failure.

        Args:
            step_id: The step identifier that was executed
        """
        if step_id not in self.executed_steps:
            self.executed_steps.append(step_id)

    def unmark_step_executed(self, step_id: str) -> None:
        """
        Remove a step from the executed list.

        Useful when a step is compensated or was rolled back.

        Args:
            step_id: The step identifier to unmark
        """
        if step_id in self.executed_steps:
            self.executed_steps.remove(step_id)

    def get_executed_steps(self) -> list[str]:
        """
        Get list of steps that were executed.

        Returns:
            List of step IDs in execution order
        """
        return self.executed_steps.copy()

    def get_compensation_order(self) -> list[list[str]]:
        """
        Compute compensation execution order respecting dependencies.

        Returns a list of levels, where each level contains steps that
        can be compensated in parallel. Levels must be executed sequentially.

        The order is the REVERSE of the dependency order because:
        - If step B depends on step A (A must run before B)
        - Then B's compensation must run BEFORE A's compensation

        Returns:
            List of levels, each level is a list of step IDs

        Raises:
            CircularDependencyError: If circular dependencies exist
        """
        to_compensate = self._get_steps_to_compensate()
        if not to_compensate:
            return []

        comp_deps = self._build_reverse_dependencies(to_compensate)
        return self._topological_sort_levels(comp_deps, set(to_compensate))

    def _get_steps_to_compensate(self) -> list[str]:
        """Get executed steps that have compensation registered."""
        return [step_id for step_id in self.executed_steps if step_id in self.nodes]

    def _build_reverse_dependencies(self, steps: list[str]) -> dict[str, set[str]]:
        """Build reverse dependency graph for compensation ordering."""
        comp_deps: dict[str, set[str]] = {}
        for step_id in steps:
            dependents = [
                other_id for other_id in steps if step_id in self.nodes[other_id].depends_on
            ]
            comp_deps[step_id] = set(dependents)
        return comp_deps

    def _topological_sort_levels(
        self, deps: dict[str, set[str]], remaining: set[str]
    ) -> list[list[str]]:
        """Perform topological sort returning levels for parallel execution."""
        levels: list[list[str]] = []
        in_degree = {step: len(d) for step, d in deps.items()}
        remaining = remaining.copy()

        while remaining:
            current_level = self._get_zero_in_degree_nodes(remaining, in_degree)
            if not current_level:
                raise CircularDependencyError(self._find_cycle(deps, remaining))
            levels.append(current_level)
            self._update_in_degrees(current_level, remaining, deps, in_degree)

        return levels

    def _get_zero_in_degree_nodes(
        self, remaining: set[str], in_degree: dict[str, int]
    ) -> list[str]:
        """Get nodes with zero in-degree from remaining set."""
        return [s for s in remaining if in_degree.get(s, 0) == 0]

    def _update_in_degrees(
        self,
        processed: list[str],
        remaining: set[str],
        deps: dict[str, set[str]],
        in_degree: dict[str, int],
    ):
        """Remove processed nodes and update in-degrees."""
        for step in processed:
            remaining.remove(step)
            for other in remaining:
                if step in deps.get(other, set()):
                    in_degree[other] -= 1

    def _find_cycle(self, deps: dict[str, set[str]], nodes: set[str]) -> list[str]:
        """Find a cycle in the dependency graph for error reporting."""
        # Simple cycle detection for error message
        visited: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> list[str] | None:
            """Depth-first search; returns closed cycle path or ``None``."""
            if node in path:
                cycle_start = path.index(node)
                return [*path[cycle_start:], node]
            if node in visited:
                return None

            visited.add(node)
            path.append(node)

            for dep in deps.get(node, set()):
                if dep in nodes:
                    result = dfs(dep)
                    if result:
                        return result

            path.pop()
            return None

        for node in nodes:
            result = dfs(node)
            if result:
                return result

        return list(nodes)[:3]  # Fallback: return first few nodes

    def validate(self) -> None:
        """
        Validate the compensation graph.

        Checks for:
            - Circular dependencies
            - Missing dependency references

        Raises:
            CircularDependencyError: If circular dependencies exist
            MissingDependencyError: If a step references non-existent dependency
        """
        self._validate_dependencies_exist()
        self._validate_no_cycles()

    def _validate_dependencies_exist(self):
        """Check all dependencies reference existing steps."""
        for step_id, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise MissingDependencyError(step_id, dep)

    def _validate_no_cycles(self):
        """Check for circular dependencies via topological sort."""
        deps: dict[str, set[str]] = {
            step_id: set(node.depends_on) for step_id, node in self.nodes.items()
        }
        # Use shared topological sort (will raise if cycle found)
        self._topological_sort_levels(deps, set(self.nodes.keys()))

    def get_compensation_info(self, step_id: str) -> CompensationNode | None:
        """
        Get compensation information for a step.

        Args:
            step_id: The step identifier

        Returns:
            CompensationNode if found, None otherwise
        """
        return self.nodes.get(step_id)

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
        import asyncio

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

    def clear(self) -> None:
        """Clear all registered compensations and executed steps."""
        self.nodes.clear()
        self.executed_steps.clear()
        self._compensation_results.clear()

    def reset_execution(self) -> None:
        """Reset executed steps while keeping compensation registrations."""
        self.executed_steps.clear()
        self._compensation_results.clear()

    def __repr__(self) -> str:
        """Return a concise summary of node count and execution progress."""
        return f"SagaExecutionGraph(nodes={len(self.nodes)}, executed={len(self.executed_steps)})"
