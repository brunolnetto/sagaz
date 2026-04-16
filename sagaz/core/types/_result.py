"""Saga execution result type."""

from dataclasses import dataclass, field
from typing import Any

from sagaz.core.types._enums import SagaStatus


@dataclass
class SagaResult:
    """
    Result of saga execution.

    Extended in v1.3.0 with pivot-aware fields:
    - pivot_reached: Whether a pivot step was successfully executed
    - committed_steps: Steps that cannot be rolled back
    - tainted_steps: Ancestors of pivots that are locked
    - forward_recovery_needed: Whether forward recovery is required
    - rollback_boundary: Step name where rollback stopped (if bounded)
    """

    success: bool
    saga_name: str
    status: SagaStatus
    completed_steps: int
    total_steps: int
    error: Exception | None = None
    execution_time: float = 0.0
    context: Any = None
    compensation_errors: list[Exception] = field(default_factory=list)

    # v1.3.0: Pivot support
    pivot_reached: bool = False
    """True if a pivot step was successfully executed."""

    committed_step_names: list[str] = field(default_factory=list)
    """Names of steps that are committed and cannot be rolled back."""

    tainted_step_names: list[str] = field(default_factory=list)
    """Names of steps that are tainted (ancestors of completed pivots)."""

    forward_recovery_needed: bool = False
    """True if forward recovery is needed for post-pivot failures."""

    rollback_boundary: str | None = None
    """Name of the pivot step where rollback stopped, if applicable."""

    @property
    def is_completed(self) -> bool:
        return self.status == SagaStatus.COMPLETED

    @property
    def is_rolled_back(self) -> bool:
        return self.status == SagaStatus.ROLLED_BACK

    @property
    def is_partially_committed(self) -> bool:
        """True if saga is partially committed (passed pivot but failed after)."""
        return self.status == SagaStatus.PARTIALLY_COMMITTED

    @property
    def needs_intervention(self) -> bool:
        """True if saga requires manual intervention for forward recovery."""
        return self.status == SagaStatus.FORWARD_RECOVERY or self.forward_recovery_needed
