"""Core SagaExecutionGraph implementation."""

from collections.abc import Awaitable, Callable
from typing import Any

from sagaz.core.execution.graph._compensation_runner import _GraphCompensationMixin
from sagaz.core.execution.graph._ordering import _GraphOrderingMixin
from sagaz.core.execution.graph._types import CompensationNode, CompensationType


class SagaExecutionGraph(_GraphOrderingMixin, _GraphCompensationMixin):
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

    def get_compensation_info(self, step_id: str) -> CompensationNode | None:
        """
        Get compensation information for a step.

        Args:
            step_id: The step identifier

        Returns:
            CompensationNode if found, None otherwise
        """
        return self.nodes.get(step_id)

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
