"""Pivot/taint mixin for the declarative Saga (v1.3.0 pivot support)."""

from typing import TYPE_CHECKING

from sagaz.core.logger import get_logger

if TYPE_CHECKING:
    from sagaz.core.decorators import SagaStepDefinition

# Keep the original logger name so log records are unchanged by the split.
logger = get_logger("sagaz.core.decorators")


class _DecoratorPivotMixin:
    """Mixin tracking pivot steps and propagating taint to their ancestors."""

    # Attributes provided by the concrete Saga host.
    _steps: list["SagaStepDefinition"]
    _completed_pivots: set[str]
    _tainted_steps: set[str]
    _pivot_reached: bool

    def get_pivot_steps(self) -> list[str]:
        """Get names of all pivot steps in this saga."""
        return [step.step_id for step in self._steps if step.pivot]

    def _get_taint_propagator(self):
        """Create a TaintPropagator for this saga."""
        from sagaz.core.execution.pivot import TaintPropagator

        step_names = {step.step_id for step in self._steps}
        dependencies = {step.step_id: set(step.depends_on) for step in self._steps}
        pivots = {step.step_id for step in self._steps if step.pivot}

        return TaintPropagator(
            step_names=step_names,
            dependencies=dependencies,
            pivots=pivots,
            completed_pivots=self._completed_pivots,
        )

    def _propagate_taint_from_pivot(self, pivot_step_id: str) -> set[str]:
        """
        Propagate taint when a pivot step completes.

        Args:
            pivot_step_id: The pivot step that just completed

        Returns:
            Set of newly tainted step names
        """
        propagator = self._get_taint_propagator()
        newly_tainted = propagator.propagate_taint(pivot_step_id)
        self._tainted_steps.update(newly_tainted)
        self._completed_pivots.add(pivot_step_id)
        self._pivot_reached = True

        if newly_tainted:
            logger.info(f"Pivot '{pivot_step_id}' completed - tainted ancestors: {newly_tainted}")

        return set(newly_tainted)

    def _is_step_tainted(self, step_id: str) -> bool:
        """Check if a step is tainted (locked from rollback)."""
        return step_id in self._tainted_steps
