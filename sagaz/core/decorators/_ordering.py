"""Execution-order mixin for the declarative Saga (topological levels of steps)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagaz.core.decorators import SagaStepDefinition


class _DecoratorOrderingMixin:
    """Mixin computing parallelisable execution levels from step dependencies."""

    # Attributes provided by the concrete Saga host.
    _steps: list[SagaStepDefinition]

    def get_execution_order(self) -> list[list[SagaStepDefinition]]:
        """
        Compute step execution order respecting dependencies.

        Returns:
            List of levels, where steps in each level can run in parallel

        Raises:
            ValueError: If circular dependencies detected
        """
        if not self._steps:
            return []

        step_map = {s.step_id: s for s in self._steps}
        in_degree = {s.step_id: len(s.depends_on) for s in self._steps}
        remaining = set(step_map.keys())

        return self._topological_sort_steps(step_map, in_degree, remaining)

    def _topological_sort_steps(
        self, step_map: dict[str, SagaStepDefinition], in_degree: dict[str, int], remaining: set
    ) -> list[list[SagaStepDefinition]]:
        """Perform topological sort on steps."""
        levels: list[list[SagaStepDefinition]] = []

        while remaining:
            current_level = [step_map[sid] for sid in remaining if in_degree[sid] == 0]
            if not current_level:
                msg = "Circular dependency detected in saga steps"
                raise ValueError(msg)
            levels.append(current_level)
            self._update_in_degrees(current_level, remaining, step_map, in_degree)

        return levels

    def _update_in_degrees(
        self,
        current_level: list[SagaStepDefinition],
        remaining: set[str],
        step_map: dict[str, SagaStepDefinition],
        in_degree: dict[str, int],
    ) -> None:
        """Update in-degrees after processing a level."""
        for step_def in current_level:
            remaining.remove(step_def.step_id)
            for other_id in remaining:
                if step_def.step_id in step_map[other_id].depends_on:
                    in_degree[other_id] -= 1
