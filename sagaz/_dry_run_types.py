"""Result types and step introspection shared by the dry-run engine (ADR-019)."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class _StepIntrospection:
    """Step extraction shared by the validation and analysis mixins."""

    def _extract_steps(self, saga: object) -> list:  # type: ignore
        """Extract steps from saga instance."""
        if hasattr(saga, "_steps") and saga._steps:
            return list(saga._steps)
        if hasattr(saga, "get_steps"):
            return list(saga.get_steps())
        if hasattr(saga, "steps"):
            return list(saga.steps)
        return []
