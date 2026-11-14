"""Execution-plan simulation and parallelization analysis for the dry-run engine (ADR-030)."""

from typing import Any

from sagaz._dry_run_types import ParallelLayerInfo, SimulationResult, _StepIntrospection


class _DryRunAnalysisMixin(_StepIntrospection):
    """Simulation phase of :class:`sagaz.dry_run.DryRunEngine`."""

    def _build_dag_from_steps(self, steps: list) -> dict[str, list[str]]:
        """Build DAG from step dependencies."""
        dag: dict[str, list[str]] = {}
        for step in steps:
            step_name: str = str(getattr(step, "step_id", None) or getattr(step, "name", "unknown"))
            depends_on: Any = getattr(step, "depends_on", set()) or getattr(
                step, "dependencies", set()
            )
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
        saga: object,
        context: dict[str, Any],  # type: ignore
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
            str(getattr(step, "step_id", None) or getattr(step, "name", "unknown"))
            for step in steps
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
        reverse_dag: dict[str, list[str]] = {node: [] for node in dag}
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
        depths: dict[str, int] = {}

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
        groups: list[list[str]] = [[] for _ in range(max_depth + 1)]

        for node, depth in depths.items():
            groups[depth].append(node)

        return [g for g in groups if g]  # Remove empty groups

    def _build_dag(self, saga: object) -> dict[str, list[str]]:  # type: ignore
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

        dag: dict[str, list[str]] = {}
        for step in steps:
            step_name: str = str(getattr(step, "step_id", None) or getattr(step, "name", "unknown"))
            depends_on: Any = getattr(step, "depends_on", set()) or getattr(
                step, "dependencies", set()
            )
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
        layers: dict[str, int] = {}

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
        longest_path: list[str] = []

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
            longest_branch: list[str] = []
            for dep in deps:
                if dep not in visited:
                    branch = self._trace_path(dep, dag, visited | {node})
                    if len(branch) > len(longest_branch):
                        longest_branch = branch
            path.extend(longest_branch)

        return path

    def _get_compensatable_steps(self, saga: object) -> set[str]:  # type: ignore
        """Get set of steps that have compensation functions."""
        steps = self._extract_steps(saga)
        compensatable_steps: set[str] = set()

        for step in steps:
            compensation_fn = getattr(step, "compensation_fn", None) or getattr(
                step, "compensation", None
            )
            if compensation_fn is not None:
                step_name: str = str(
                    getattr(step, "step_id", None) or getattr(step, "name", "unknown")
                )
                compensatable_steps.add(step_name)

        return compensatable_steps

    def _analyze_backward_layers(
        self,
        saga: object,  # type: ignore
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
