"""
Dry-Run Simulation Mode (ADR-019)

Validates and previews saga execution without side effects.
Provides validation, simulation, estimation, and tracing capabilities.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sagaz.core.types import SagaStatus


@dataclass
class ParallelLayerInfo:
    """Information about a parallelizable execution layer."""

    layer_number: int
    steps: list[str]
    dependencies: set[str] = field(default_factory=set)  # Steps from previous layers


class DryRunMode(Enum):
    """Dry-run execution modes.

    - VALIDATE: Configuration validation only
    - SIMULATE: Preview step execution order with parallelization analysis
    """

    VALIDATE = "validate"
    SIMULATE = "simulate"


@dataclass
class DryRunResult:
    """Result of dry-run execution.

    Contains validation results, execution plan, and parallelization analysis.
    """

    mode: DryRunMode
    success: bool

    # Validation results
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    validation_checks: dict[str, bool] = field(default_factory=dict)  # What was validated

    # Execution plan (SIMULATE mode)
    steps_planned: list[str] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)
    parallel_groups: list[list[str]] = field(default_factory=list)

    # Parallel execution analysis (ADR-030)
    forward_layers: list[ParallelLayerInfo] = field(default_factory=list)
    backward_layers: list[ParallelLayerInfo] = field(default_factory=list)

    # Parallelization metrics
    total_layers: int = 0
    max_parallel_width: int = 0
    critical_path: list[str] = field(default_factory=list)
    parallelization_ratio: float = 1.0

    # Complexity (works without metadata)
    sequential_complexity: int = 0
    parallel_complexity: int = 0

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of saga validation."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)  # What was validated

    @property
    def is_valid(self) -> bool:
        """Check if validation passed."""
        return len(self.errors) == 0


@dataclass
class SimulationResult:
    """Result of saga simulation."""

    steps: list[str]
    order: list[str]
    parallel_groups: list[list[str]] = field(default_factory=list)


class DryRunEngine:
    """Execute sagas in dry-run mode without side effects.

    Provides validation and simulation without executing actual step actions.

    Example:
        >>> engine = DryRunEngine()
        >>> result = await engine.run(saga, context, DryRunMode.VALIDATE)
        >>> if not result.success:
        ...     print(f"Errors: {result.validation_errors}")
    """

    def __init__(self):
        """Initialize dry-run engine."""

    async def run(
        self,
        saga: "Saga",
        context: dict[str, Any],
        mode: DryRunMode,  # type: ignore # noqa: F821
    ) -> DryRunResult:
        """Run saga in dry-run mode.

        Args:
            saga: Saga instance to dry-run
            context: Saga context
            mode: Dry-run mode to execute

        Returns:
            DryRunResult with validation or simulation analysis
        """
        result = DryRunResult(mode=mode, success=True)

        # Phase 1: Validation (always run)
        validation = await self._validate(saga, context)
        result.validation_errors = validation.errors
        result.validation_warnings = validation.warnings
        result.validation_checks = validation.checks

        if not validation.is_valid:
            result.success = False
            return result

        # Phase 2: Mode-specific execution
        if mode == DryRunMode.VALIDATE:
            return result

        if mode == DryRunMode.SIMULATE:
            simulation = await self._simulate(saga, context)
            result.steps_planned = simulation.steps
            result.execution_order = simulation.order
            result.parallel_groups = simulation.parallel_groups

            # Enhanced parallel analysis (ADR-030)
            dag = self._build_dag(saga)
            result.forward_layers, result.critical_path = self._analyze_parallel_layers(dag)
            result.backward_layers = self._analyze_backward_layers(saga, result.forward_layers)
            result.total_layers = len(result.forward_layers)
            result.max_parallel_width = max(
                (len(layer.steps) for layer in result.forward_layers), default=1
            )
            result.sequential_complexity = len(result.steps_planned)
            result.parallel_complexity = result.total_layers
            result.parallelization_ratio = (
                result.parallel_complexity / result.sequential_complexity
                if result.sequential_complexity > 0
                else 1.0
            )

        return result

    async def _validate(
        self,
        saga: "Saga",
        context: dict[str, Any],  # type: ignore # noqa: F821
    ) -> ValidationResult:
        """Validate saga configuration."""
        errors = []
        warnings = []
        checks = {}

        steps = self._extract_steps(saga)
        if not steps:
            errors.append("Saga has no steps defined")
            checks["has_steps"] = False
            return ValidationResult(errors=errors, warnings=warnings, checks=checks)

        checks["has_steps"] = True
        checks["step_count"] = len(steps)
        step_names = self._get_step_names(steps)
        checks["step_names"] = sorted(step_names)

        has_dependencies, has_compensation = self._validate_steps(
            steps, step_names, errors, warnings
        )
        checks["has_dependencies"] = has_dependencies
        checks["has_compensation"] = has_compensation

        self._validate_context_fields(saga, context, checks, errors)
        self._validate_cycles(steps, checks, errors)

        return ValidationResult(errors=errors, warnings=warnings, checks=checks)

    def _extract_steps(self, saga: "Saga") -> list:  # type: ignore # noqa: F821
        """Extract steps from saga."""
        if hasattr(saga, "_steps") and saga._steps:
            return saga._steps
        if hasattr(saga, "get_steps"):
            return saga.get_steps()
        if hasattr(saga, "steps"):
            return saga.steps
        return []

    def _get_step_names(self, steps: list) -> set[str]:
        """Get step names from steps."""
        return {getattr(step, "step_id", None) or getattr(step, "name", "") for step in steps}

    def _validate_steps(
        self, steps: list, step_names: set[str], errors: list, warnings: list
    ) -> tuple[bool, bool]:
        """Validate individual steps and return (has_dependencies, has_compensation)."""
        has_dependencies = False
        has_compensation = False

        for step in steps:
            step_name = getattr(step, "step_id", None) or getattr(step, "name", "unknown")
            depends_on = getattr(step, "depends_on", set()) or getattr(step, "dependencies", set())

            if depends_on:
                has_dependencies = True
                for dep in depends_on:
                    if dep not in step_names:
                        errors.append(f"Step '{step_name}' depends on unknown step '{dep}'")

            compensation_fn = getattr(step, "compensation_fn", None) or getattr(
                step, "compensation", None
            )
            if compensation_fn is not None:
                has_compensation = True
            elif getattr(step, "requires_compensation", False):
                warnings.append(f"Step '{step_name}' requires compensation but none defined")

        return has_dependencies, has_compensation

    def _validate_context_fields(
        self,
        saga: "Saga",
        context: dict[str, Any],
        checks: dict,
        errors: list,  # type: ignore # noqa: F821
    ):
        """Validate required context fields."""
        checks["required_context_fields"] = []
        if hasattr(saga, "required_context_fields"):
            checks["required_context_fields"] = list(saga.required_context_fields)
            missing = set(saga.required_context_fields) - set(context.keys())
            if missing:
                errors.append(f"Missing required context fields: {sorted(missing)}")

    def _validate_cycles(self, steps: list, checks: dict, errors: list):
        """Build DAG and check for cycles."""
        dag = {}
        for step in steps:
            step_name = getattr(step, "step_id", None) or getattr(step, "name", "unknown")
            depends_on = getattr(step, "depends_on", set()) or getattr(step, "dependencies", set())
            dag[step_name] = list(depends_on) if depends_on else []

        checks["has_cycles"] = False
        if dag and any(deps for deps in dag.values()):
            cycles = self._detect_cycles(dag)
            if cycles:
                checks["has_cycles"] = True
                errors.append(f"Circular dependencies detected: {cycles}")

    def _detect_cycles(self, dag: dict[str, list[str]]) -> list[list[str]]:
        """Detect cycles in DAG using DFS.

        Args:
            dag: Adjacency list representation {step: [dependencies]}

        Returns:
            List of cycles found (empty if no cycles)
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: list[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in dag.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path[:])
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append([*path[cycle_start:], neighbor])

            rec_stack.remove(node)

        for node in dag:
            if node not in visited:
                dfs(node, [])

        return cycles

    def _extract_steps(self, saga: "Saga") -> list:  # type: ignore # noqa: F821
        """Extract steps from saga instance."""
        if hasattr(saga, "_steps") and saga._steps:
            return saga._steps
        if hasattr(saga, "get_steps"):
            return saga.get_steps()
        if hasattr(saga, "steps"):
            return saga.steps
        return []

    def _build_dag_from_steps(self, steps: list) -> dict[str, list[str]]:
        """Build DAG from step dependencies."""
        dag = {}
        for step in steps:
            step_name = getattr(step, "step_id", None) or getattr(step, "name", "unknown")
            depends_on = getattr(step, "depends_on", set()) or getattr(step, "dependencies", set())
            dag[step_name] = list(depends_on) if depends_on else []
        return dag

    def _determine_execution_plan(
        self, dag: dict[str, list[str]], steps_planned: list[str]
    ) -> tuple[list[str], list[list[str]]]:
        """Determine execution order and parallel groups."""
        if dag and any(deps for deps in dag.values()):
            execution_order = self._topological_sort(dag)
            parallel_groups = self._identify_parallel_groups(dag)
        else:
            execution_order = steps_planned
            parallel_groups = [[s] for s in execution_order]
        return execution_order, parallel_groups

    async def _simulate(
        self,
        saga: "Saga",
        context: dict[str, Any],  # type: ignore # noqa: F821
    ) -> SimulationResult:
        """Simulate saga execution to preview step order.

        Args:
            saga: Saga to simulate
            context: Execution context

        Returns:
            SimulationResult with steps, order, and parallel groups
        """
        steps = self._extract_steps(saga)
        steps_planned = [
            getattr(step, "step_id", None) or getattr(step, "name", "unknown") for step in steps
        ]
        dag = self._build_dag_from_steps(steps)
        execution_order, parallel_groups = self._determine_execution_plan(dag, steps_planned)

        return SimulationResult(
            steps=steps_planned, order=execution_order, parallel_groups=parallel_groups
        )

    def _build_reverse_dag(
        self, dag: dict[str, list[str]]
    ) -> tuple[dict[str, list[str]], dict[str, int]]:
        """Build reverse DAG and compute in-degrees."""
        reverse_dag = {node: [] for node in dag}
        in_degree = {node: len(dag[node]) for node in dag}

        for node, dependencies in dag.items():
            for dep in dependencies:
                if dep not in reverse_dag:
                    reverse_dag[dep] = []
                    in_degree[dep] = 0
                reverse_dag[dep].append(node)

        return reverse_dag, in_degree

    def _topological_sort(self, dag: dict[str, list[str]]) -> list[str]:
        """Topological sort of DAG for execution order.

        Args:
            dag: Adjacency list {step: [dependencies]} where dag[A] = [B] means "A depends on B"

        Returns:
            List of steps in execution order
        """
        reverse_dag, in_degree = self._build_reverse_dag(dag)
        queue = [node for node in dag if in_degree[node] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for dependent in reverse_dag.get(node, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return result

    def _identify_parallel_groups(self, dag: dict[str, list[str]]) -> list[list[str]]:
        """Identify steps that can run in parallel.

        Args:
            dag: Adjacency list {step: [dependencies]}

        Returns:
            List of parallel groups [[step1, step2], [step3], ...]
        """
        # Simple implementation: group steps with same depth
        depths = {}

        def calculate_depth(node: str, memo: dict[str, int]) -> int:
            if node in memo:
                return memo[node]

            if not dag.get(node):
                memo[node] = 0
                return 0

            max_dep_depth = max((calculate_depth(dep, memo) for dep in dag[node]), default=-1)
            memo[node] = max_dep_depth + 1
            return memo[node]

        for node in dag:
            calculate_depth(node, depths)

        # Group by depth
        max_depth = max(depths.values()) if depths else 0
        groups = [[] for _ in range(max_depth + 1)]

        for node, depth in depths.items():
            groups[depth].append(node)

        return [g for g in groups if g]  # Remove empty groups

    def _build_dag(self, saga: "Saga") -> dict[str, list[str]]:  # type: ignore # noqa: F821
        """Build DAG from saga steps.

        Args:
            saga: Saga instance

        Returns:
            DAG as adjacency list {step: [dependencies]}
        """
        steps = []
        if hasattr(saga, "_steps") and saga._steps:
            steps = saga._steps
        elif hasattr(saga, "get_steps"):
            steps = saga.get_steps()
        elif hasattr(saga, "steps"):
            steps = saga.steps

        dag = {}
        for step in steps:
            step_name = getattr(step, "step_id", None) or getattr(step, "name", "unknown")
            depends_on = getattr(step, "depends_on", set()) or getattr(step, "dependencies", set())
            dag[step_name] = list(depends_on) if depends_on else []

        return dag

    def _analyze_parallel_layers(
        self, dag: dict[str, list[str]]
    ) -> tuple[list[ParallelLayerInfo], list[str]]:
        """Analyze DAG for parallelizable execution layers (ADR-030).

        This identifies which steps can run in parallel by grouping them into layers
        based on their dependency depth. Steps in the same layer can execute concurrently.

        Args:
            dag: Adjacency list {step: [dependencies]}

        Returns:
            - List of forward execution layers with dependency info
            - Critical path (longest dependency chain)
        """
        # Calculate layer depth for each node
        layers = {}

        def calculate_depth(node: str, memo: dict[str, int]) -> int:
            if node in memo:
                return memo[node]

            if not dag.get(node):
                memo[node] = 0
                return 0

            max_dep_depth = max((calculate_depth(dep, memo) for dep in dag[node]), default=-1)
            memo[node] = max_dep_depth + 1
            return memo[node]

        for node in dag:
            calculate_depth(node, layers)

        # Group steps by layer
        max(layers.values()) if layers else 0
        layer_groups: dict[int, list[str]] = {}

        for step, layer in layers.items():
            if layer not in layer_groups:
                layer_groups[layer] = []
            layer_groups[layer].append(step)

        # Build layer info with dependencies
        forward_layers = []
        for layer_num in sorted(layer_groups.keys()):
            steps = layer_groups[layer_num]

            # Find all dependencies for this layer (from previous layers)
            deps = set()
            for step in steps:
                deps.update(dag.get(step, []))

            forward_layers.append(
                ParallelLayerInfo(
                    layer_number=layer_num,
                    steps=sorted(steps),
                    dependencies=deps,
                )
            )

        # Find critical path (longest chain)
        critical_path = self._find_critical_path(dag, layers)

        return forward_layers, critical_path

    def _find_critical_path(self, dag: dict[str, list[str]], layers: dict[str, int]) -> list[str]:
        """Find the longest dependency chain (critical path).

        Args:
            dag: Adjacency list {step: [dependencies]}
            layers: Layer depth for each step

        Returns:
            List of steps forming the critical path
        """
        if not layers:
            return []

        # Start from deepest layer
        max_layer = max(layers.values())
        deepest_nodes = [node for node, layer in layers.items() if layer == max_layer]

        # Trace back dependencies to find longest path
        longest_path = []

        for start_node in deepest_nodes:
            path = self._trace_path(start_node, dag, set())
            if len(path) > len(longest_path):
                longest_path = path

        return list(reversed(longest_path))

    def _trace_path(self, node: str, dag: dict[str, list[str]], visited: set[str]) -> list[str]:
        """Recursively trace dependency path.

        Args:
            node: Current node
            dag: Adjacency list
            visited: Set of visited nodes (avoid cycles)

        Returns:
            Path from node to root
        """
        path = [node]

        deps = dag.get(node, [])
        if deps:
            # Follow the longest dependency branch
            longest_branch = []
            for dep in deps:
                if dep not in visited:
                    branch = self._trace_path(dep, dag, visited | {node})
                    if len(branch) > len(longest_branch):
                        longest_branch = branch
            path.extend(longest_branch)

        return path

    def _get_compensatable_steps(self, saga: "Saga") -> set[str]:  # type: ignore # noqa: F821
        """Get set of steps that have compensation functions."""
        steps = self._extract_steps(saga)
        compensatable_steps = set()

        for step in steps:
            compensation_fn = getattr(step, "compensation_fn", None) or getattr(
                step, "compensation", None
            )
            if compensation_fn is not None:
                step_name = getattr(step, "step_id", None) or getattr(step, "name", "unknown")
                compensatable_steps.add(step_name)

        return compensatable_steps

    def _analyze_backward_layers(
        self,
        saga: "Saga",  # type: ignore # noqa: F821
        forward_layers: list[ParallelLayerInfo],
    ) -> list[ParallelLayerInfo]:
        """Analyze compensation (backward) execution layers.

        Compensation happens in reverse order: deepest layer first.

        Args:
            saga: Saga instance
            forward_layers: Forward execution layers

        Returns:
            List of backward compensation layers
        """
        compensatable_steps = self._get_compensatable_steps(saga)
        backward_layers = []

        for i, forward_layer in enumerate(reversed(forward_layers)):
            compensatable_in_layer = [
                step for step in forward_layer.steps if step in compensatable_steps
            ]

            if compensatable_in_layer:
                backward_layers.append(
                    ParallelLayerInfo(
                        layer_number=i,
                        steps=compensatable_in_layer,
                        dependencies=set(),
                    )
                )

        return backward_layers
