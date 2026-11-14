"""
Dry-Run Simulation Mode (ADR-019)

Validates and previews saga execution without side effects.
Provides validation, simulation, estimation, and tracing capabilities.

The result types, the validation phase and the simulation/parallelization
analysis live in private sibling modules; the public names are re-exported here.
"""

from typing import Any

from sagaz._dry_run_analysis import _DryRunAnalysisMixin
from sagaz._dry_run_types import (
    DryRunMode,
    DryRunResult,
    ParallelLayerInfo,
    SimulationResult,
    ValidationResult,
)
from sagaz._dry_run_validation import _DryRunValidationMixin

__all__ = [
    "DryRunEngine",
    "DryRunMode",
    "DryRunResult",
    "ParallelLayerInfo",
    "SimulationResult",
    "ValidationResult",
]


class DryRunEngine(_DryRunValidationMixin, _DryRunAnalysisMixin):
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
        saga: object,
        context: dict[str, Any],
        mode: DryRunMode,  # type: ignore
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
