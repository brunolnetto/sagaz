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


class DryRunMode(Enum):
    """Dry-run execution modes.
    
    - VALIDATE: Configuration validation only
    - SIMULATE: Preview step execution order
    - ESTIMATE: Resource usage estimation  
    - TRACE: Detailed execution trace
    """

    VALIDATE = "validate"
    SIMULATE = "simulate"
    ESTIMATE = "estimate"
    TRACE = "trace"


@dataclass
class DryRunTraceEvent:
    """Event in dry-run execution trace."""

    step_name: str
    action: str  # "execute", "compensate", "skip"
    context_before: dict[str, Any]
    context_after: dict[str, Any]
    estimated_duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DryRunResult:
    """Result of dry-run execution.
    
    Contains validation results, execution plan, resource estimates,
    and optional detailed trace.
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
    max_parallel_duration_ms: float = 0.0  # Upper bound with parallelism

    # Resource estimates (ESTIMATE mode)
    estimated_duration_ms: float = 0.0  # Sequential duration
    estimated_duration_parallel_ms: float = 0.0  # With parallelism
    api_calls_estimated: dict[str, int] = field(default_factory=dict)
    cost_estimate_usd: float = 0.0

    # Detailed trace (TRACE mode)
    trace: list[DryRunTraceEvent] | None = None

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


@dataclass
class EstimateResult:
    """Result of resource estimation."""

    duration_ms: float
    api_calls: dict[str, int]
    cost_usd: float = 0.0


@dataclass
class TraceResult:
    """Result of execution tracing."""

    events: list[DryRunTraceEvent]


class DryRunEngine:
    """Execute sagas in dry-run mode without side effects.
    
    Provides validation, simulation, estimation, and tracing
    without executing actual step actions.
    
    Example:
        >>> engine = DryRunEngine()
        >>> result = await engine.run(saga, context, DryRunMode.VALIDATE)
        >>> if not result.success:
        ...     print(f"Errors: {result.validation_errors}")
    """

    def __init__(self):
        """Initialize dry-run engine."""
        self._api_pricing: dict[str, float] = {}  # API name -> cost per call (USD)

    def set_api_pricing(self, api: str, cost_per_call: float):
        """Set pricing for API cost estimation.
        
        Args:
            api: API service name
            cost_per_call: Cost per API call in USD
        """
        self._api_pricing[api] = cost_per_call

    async def run(
        self, saga: "Saga", context: dict[str, Any], mode: DryRunMode  # type: ignore # noqa: F821
    ) -> DryRunResult:
        """Run saga in dry-run mode.
        
        Args:
            saga: Saga instance to dry-run
            context: Saga context
            mode: Dry-run mode to execute
            
        Returns:
            DryRunResult with validation, simulation, estimates, or trace
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

        elif mode == DryRunMode.SIMULATE:
            simulation = await self._simulate(saga, context)
            result.steps_planned = simulation.steps
            result.execution_order = simulation.order
            result.parallel_groups = simulation.parallel_groups
            # Calculate max parallel duration
            result.max_parallel_duration_ms = self._calculate_parallel_duration(
                saga, simulation.parallel_groups
            )

        elif mode == DryRunMode.ESTIMATE:
            estimate = await self._estimate(saga, context)
            result.estimated_duration_ms = estimate.duration_ms
            result.api_calls_estimated = estimate.api_calls
            result.cost_estimate_usd = estimate.cost_usd
            # Also calculate parallel duration
            simulation = await self._simulate(saga, context)
            result.estimated_duration_parallel_ms = self._calculate_parallel_duration(
                saga, simulation.parallel_groups
            )

        elif mode == DryRunMode.TRACE:
            trace = await self._trace(saga, context)
            result.trace = trace.events

        return result

    async def _validate(
        self, saga: "Saga", context: dict[str, Any]  # type: ignore # noqa: F821
    ) -> ValidationResult:
        """Validate saga configuration.
        
        Checks:
        - DAG for cycles (if DAG saga)
        - Required context fields
        - Compensation availability
        - Step dependencies
        
        Args:
            saga: Saga to validate
            context: Context to validate against
            
        Returns:
            ValidationResult with errors and warnings
        """
        errors = []
        warnings = []

        # 1. Check if saga has steps
        steps = []
        
        # Try declarative Saga (from decorators.py)
        if hasattr(saga, '_steps') and saga._steps:
            steps = saga._steps
        # Try imperative Saga (from core/saga.py)
        elif hasattr(saga, 'get_steps'):
            steps = saga.get_steps()
        elif hasattr(saga, 'steps'):
            steps = saga.steps
        
        checks = {}
            
        if not steps:
            errors.append("Saga has no steps defined")
            checks["has_steps"] = False
            return ValidationResult(errors=errors, warnings=warnings, checks=checks)
        
        checks["has_steps"] = True
        checks["step_count"] = len(steps)

        # 2. Get step names for dependency validation
        # Declarative saga uses step_id, imperative uses name
        step_names = {getattr(step, 'step_id', None) or getattr(step, 'name', '') for step in steps}
        checks["step_names"] = sorted(step_names)

        # 3. Validate each step
        has_dependencies = False
        has_compensation = False
        
        for step in steps:
            step_name = getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown')
            
            # Check dependencies (declarative saga uses depends_on, imperative uses dependencies)
            depends_on = getattr(step, 'depends_on', set()) or getattr(step, 'dependencies', set())
            if depends_on:
                has_dependencies = True
                for dep in depends_on:
                    if dep not in step_names:
                        errors.append(
                            f"Step '{step_name}' depends on unknown step '{dep}'"
                        )
            
            # Check compensation if step is compensatable
            compensation_fn = getattr(step, 'compensation_fn', None) or getattr(step, 'compensation', None)
            if compensation_fn is not None:
                has_compensation = True
            else:
                # Check if compensation is required
                if getattr(step, 'requires_compensation', False):
                    warnings.append(
                        f"Step '{step_name}' requires compensation but none defined"
                    )
        
        checks["has_dependencies"] = has_dependencies
        checks["has_compensation"] = has_compensation

        # 4. Check for required context fields (if defined in saga metadata)
        checks["required_context_fields"] = []
        if hasattr(saga, "required_context_fields"):
            checks["required_context_fields"] = list(saga.required_context_fields)
            missing = set(saga.required_context_fields) - set(context.keys())
            if missing:
                errors.append(f"Missing required context fields: {sorted(missing)}")

        # 5. Build DAG and check for cycles
        dag = {}
        for step in steps:
            step_name = getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown')
            depends_on = getattr(step, 'depends_on', set()) or getattr(step, 'dependencies', set())
            dag[step_name] = list(depends_on) if depends_on else []
        
        checks["has_cycles"] = False
        if dag and any(deps for deps in dag.values()):
            cycles = self._detect_cycles(dag)
            if cycles:
                checks["has_cycles"] = True
                errors.append(f"Circular dependencies detected: {cycles}")

        return ValidationResult(errors=errors, warnings=warnings, checks=checks)

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
                    cycles.append(path[cycle_start:] + [neighbor])

            rec_stack.remove(node)

        for node in dag:
            if node not in visited:
                dfs(node, [])

        return cycles

    async def _simulate(
        self, saga: "Saga", context: dict[str, Any]  # type: ignore # noqa: F821
    ) -> SimulationResult:
        """Simulate saga execution to preview step order.
        
        Args:
            saga: Saga to simulate
            context: Execution context
            
        Returns:
            SimulationResult with steps, order, and parallel groups
        """
        # Get steps (support both declarative and imperative sagas)
        steps = []
        if hasattr(saga, '_steps') and saga._steps:
            steps = saga._steps
        elif hasattr(saga, 'get_steps'):
            steps = saga.get_steps()
        elif hasattr(saga, 'steps'):
            steps = saga.steps
            
        steps_planned = [getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown') for step in steps]

        # Build DAG from step dependencies
        dag = {}
        for step in steps:
            step_name = getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown')
            depends_on = getattr(step, 'depends_on', set()) or getattr(step, 'dependencies', set())
            dag[step_name] = list(depends_on) if depends_on else []

        # Determine execution order
        # Check for DAG (declarative saga builds DAG from depends_on)
        if dag and any(deps for deps in dag.values()):
            # DAG saga - topological sort
            execution_order = self._topological_sort(dag)
            parallel_groups = self._identify_parallel_groups(dag)
        else:
            # Sequential saga
            execution_order = steps_planned
            parallel_groups = [[s] for s in execution_order]

        return SimulationResult(
            steps=steps_planned, order=execution_order, parallel_groups=parallel_groups
        )

    def _topological_sort(self, dag: dict[str, list[str]]) -> list[str]:
        """Topological sort of DAG for execution order.
        
        Args:
            dag: Adjacency list {step: [dependencies]} where dag[A] = [B] means "A depends on B"
            
        Returns:
            List of steps in execution order
        """
        # Build reverse DAG: {node: [nodes_that_depend_on_it]}
        reverse_dag = {node: [] for node in dag}
        in_degree = {node: len(dag[node]) for node in dag}
        
        for node, dependencies in dag.items():
            for dep in dependencies:
                if dep not in reverse_dag:
                    reverse_dag[dep] = []
                    in_degree[dep] = 0
                reverse_dag[dep].append(node)

        # Kahn's algorithm on original DAG (start with nodes that have no dependencies)
        queue = [node for node in dag if in_degree[node] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            # For each node that depends on this node
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

            max_dep_depth = max(
                (calculate_depth(dep, memo) for dep in dag[node]), default=-1
            )
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

    async def _estimate(
        self, saga: "Saga", context: dict[str, Any]  # type: ignore # noqa: F821
    ) -> EstimateResult:
        """Estimate resource usage.
        
        Args:
            saga: Saga to estimate
            context: Execution context
            
        Returns:
            EstimateResult with duration, API calls, and cost
        """
        # Get steps (support both declarative and imperative sagas)
        steps = []
        if hasattr(saga, '_steps') and saga._steps:
            steps = saga._steps
        elif hasattr(saga, 'get_steps'):
            steps = saga.get_steps()
        elif hasattr(saga, 'steps'):
            steps = saga.steps
            
        duration_ms = 0.0
        api_calls = defaultdict(int)

        for step in steps:
            # Get step action/forward function
            action_fn = getattr(step, 'forward_fn', None) or getattr(step, 'action', None)
            if action_fn is None:
                continue
                
            # Get step metadata for estimates
            metadata = getattr(action_fn, "__sagaz_metadata__", {})

            # Estimate duration
            estimated_time = metadata.get("estimated_duration_ms", 100)
            duration_ms += estimated_time

            # Count API calls
            for api, count in metadata.get("api_calls", {}).items():
                api_calls[api] += count

        # Calculate cost
        cost_usd = self._calculate_cost(dict(api_calls))

        return EstimateResult(
            duration_ms=duration_ms, api_calls=dict(api_calls), cost_usd=cost_usd
        )

    def _calculate_cost(self, api_calls: dict[str, int]) -> float:
        """Calculate cost based on API pricing.
        
        Args:
            api_calls: Dictionary of {api: call_count}
            
        Returns:
            Total cost in USD
        """
        total = 0.0
        for api, count in api_calls.items():
            if api in self._api_pricing:
                total += count * self._api_pricing[api]
        return total

    async def _trace(
        self, saga: "Saga", context: dict[str, Any]  # type: ignore # noqa: F821
    ) -> TraceResult:
        """Generate detailed execution trace.
        
        Args:
            saga: Saga to trace
            context: Execution context
            
        Returns:
            TraceResult with detailed event trace
        """
        # Get steps (support both declarative and imperative sagas)
        steps = []
        if hasattr(saga, '_steps') and saga._steps:
            steps = saga._steps
        elif hasattr(saga, 'get_steps'):
            steps = saga.get_steps()
        elif hasattr(saga, 'steps'):
            steps = saga.steps
            
        events = []
        current_context = context.copy()

        for step in steps:
            step_name = getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown')
            
            # Get step action/forward function
            action_fn = getattr(step, 'forward_fn', None) or getattr(step, 'action', None)
            if action_fn is None:
                continue
                
            # Get metadata
            metadata = getattr(action_fn, "__sagaz_metadata__", {})
            estimated_duration = metadata.get("estimated_duration_ms", 100)

            # Mock step result
            context_after = current_context.copy()
            context_after[f"{step_name}_result"] = "dry-run-mock"

            # Create trace event
            event = DryRunTraceEvent(
                step_name=step_name,
                action="execute",
                context_before=current_context.copy(),
                context_after=context_after.copy(),
                estimated_duration_ms=estimated_duration,
                metadata=metadata.copy() if metadata else {},
            )
            events.append(event)

            current_context = context_after

        return TraceResult(events=events)
    
    def _calculate_parallel_duration(
        self, saga: "Saga", parallel_groups: list[list[str]]  # type: ignore # noqa: F821
    ) -> float:
        """Calculate maximum duration considering parallel execution.
        
        For each parallel group, takes the MAX duration (longest step in group).
        Total duration is SUM of max durations across groups.
        
        Args:
            saga: Saga instance
            parallel_groups: List of parallel execution groups
            
        Returns:
            Upper bound duration in milliseconds with parallelism
        """
        # Build step name -> duration map
        steps = []
        if hasattr(saga, '_steps') and saga._steps:
            steps = saga._steps
        elif hasattr(saga, 'get_steps'):
            steps = saga.get_steps()
        elif hasattr(saga, 'steps'):
            steps = saga.steps
        
        step_durations = {}
        for step in steps:
            step_name = getattr(step, 'step_id', None) or getattr(step, 'name', 'unknown')
            action_fn = getattr(step, 'forward_fn', None) or getattr(step, 'action', None)
            
            if action_fn:
                metadata = getattr(action_fn, "__sagaz_metadata__", {})
                duration = metadata.get("estimated_duration_ms", 100)
                step_durations[step_name] = duration
        
        # Calculate max duration per group, sum across groups
        total_duration = 0.0
        for group in parallel_groups:
            # In parallel group, execution takes as long as the slowest step
            group_max = max(
                (step_durations.get(step_name, 100) for step_name in group),
                default=100
            )
            total_duration += group_max
        
        return total_duration
