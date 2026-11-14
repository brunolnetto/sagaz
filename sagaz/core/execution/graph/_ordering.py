"""Ordering/validation mixin for ``SagaExecutionGraph`` (topological levels, cycles)."""

from sagaz.core.execution.graph._exceptions import CircularDependencyError, MissingDependencyError
from sagaz.core.execution.graph._types import CompensationNode


class _GraphOrderingMixin:
    """Mixin computing compensation order and validating the dependency graph."""

    # Attributes provided by the concrete graph host.
    nodes: dict[str, CompensationNode]
    executed_steps: list[str]

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
