"""
Compensation dependency graph management.

Provides flexible compensation ordering based on step dependencies,
enabling parallel compensation execution where safe.

Example:
    >>> graph = SagaCompensationGraph()
    >>> graph.register_compensation("create_order", cancel_order)
    >>> graph.register_compensation("charge_payment", refund_payment, depends_on=["create_order"])
    >>>
    >>> # When failure occurs, execute compensations in dependency order:
    >>> levels = graph.get_compensation_order()
    >>> for level in levels:
    ...     await asyncio.gather(*[execute_compensation(step) for step in level])
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CompensationType(Enum):
    """Type of compensation action."""

    MECHANICAL = "mechanical"
    """Pure rollback - undo exactly what was done (e.g., delete created record)"""

    SEMANTIC = "semantic"
    """Business logic compensation - may differ from exact reverse (e.g., issue refund credit)"""

    MANUAL = "manual"
    """Requires human intervention (e.g., review by support team)"""


@dataclass
class CompensationNode:
    """
    Node in compensation dependency graph.

    Represents a single compensation action with its dependencies
    and metadata for execution.

    Attributes:
        step_id: Unique identifier for this step
        compensation_fn: Async function to execute compensation
        depends_on: List of step IDs that must be compensated first
        compensation_type: Type of compensation (mechanical, semantic, manual)
        description: Human-readable description for logging/monitoring
        max_retries: Maximum retry attempts for this compensation
        timeout_seconds: Timeout for compensation execution
    """

    step_id: str
    compensation_fn: Callable[[dict[str, Any]], Awaitable[None]]
    depends_on: list[str] = field(default_factory=list)
    compensation_type: CompensationType = CompensationType.MECHANICAL
    description: str | None = None
    max_retries: int = 3
    timeout_seconds: float = 30.0


class CompensationGraphError(Exception):
    """Base exception for compensation graph errors."""


class CircularDependencyError(CompensationGraphError):
    """Raised when circular dependencies are detected in the graph."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class MissingDependencyError(CompensationGraphError):
    """Raised when a step depends on a non-existent step."""

    def __init__(self, step_id: str, missing_dep: str):
        self.step_id = step_id
        self.missing_dep = missing_dep
        super().__init__(f"Step '{step_id}' depends on non-existent step '{missing_dep}'")


class SagaCompensationGraph:
    """
    Manages compensation dependencies and execution order.

    The compensation graph allows defining complex compensation relationships
    where certain compensations must complete before others can begin.

    Key Features:
        - Parallel execution of independent compensations
        - Dependency-based ordering (topological sort)
        - Supports different compensation types
        - Tracks executed steps for accurate compensation

    Usage:
        >>> graph = SagaCompensationGraph()
        >>>
        >>> # Register compensations with dependencies
        >>> graph.register_compensation("step1", undo_step1)
        >>> graph.register_compensation("step2", undo_step2, depends_on=["step1"])
        >>> graph.register_compensation("step3", undo_step3, depends_on=["step1", "step2"])
        >>>
        >>> # Mark steps as executed during saga execution
        >>> graph.mark_step_executed("step1")
        >>> graph.mark_step_executed("step2")
        >>>
        >>> # Get compensation order (only executed steps)
        >>> levels = graph.get_compensation_order()
        >>> # Returns: [["step2"], ["step1"]]
        >>> # step2 has dependency on step1, so step1 compensates AFTER step2
    """

    def __init__(self):
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

        Args:
            step_id: Unique identifier for this step
            compensation_fn: Async function(context) to execute on compensation
            depends_on: Steps that must be compensated BEFORE this one
            compensation_type: Type of compensation action
            description: Optional description for logging
            max_retries: Max retry attempts (default: 3)
            timeout_seconds: Execution timeout (default: 30s)

        Example:
            >>> async def refund_payment(ctx):
            ...     await PaymentService.refund(ctx["charge_id"])
            >>>
            >>> graph.register_compensation(
            ...     "charge_payment",
            ...     refund_payment,
            ...     depends_on=["create_order"],  # Refund after order cancelled
            ...     compensation_type=CompensationType.SEMANTIC,
            ...     description="Refund customer payment"
            ... )
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
        return (
            f"SagaCompensationGraph(nodes={len(self.nodes)}, executed={len(self.executed_steps)})"
        )
