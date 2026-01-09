# ============================================
# FILE: saga/types.py
# ============================================

"""
All type definitions, enums, and dataclasses

Extended in v1.3.0 with pivot/irreversible step support:
- PARTIALLY_COMMITTED and FORWARD_RECOVERY saga statuses
- Pivot-aware fields in SagaResult
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SagaStatus(Enum):
    """
    Overall saga status.

    Extended in v1.3.0 with pivot support:
    - PARTIALLY_COMMITTED: Saga passed a pivot but failed after
    - FORWARD_RECOVERY: Saga needs forward recovery handling
    """

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

    # v1.3.0: Pivot support
    PARTIALLY_COMMITTED = "partially_committed"
    """Saga passed a pivot but failed after. Partial rollback was performed."""

    FORWARD_RECOVERY = "forward_recovery"
    """Saga needs forward recovery handling (waiting for manual intervention or retry)."""


class SagaStepStatus(Enum):
    """Status of individual saga step"""

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"

    # v1.3.0: Pivot support
    TAINTED = "tainted"
    """Step is tainted (ancestor of completed pivot) and cannot be compensated."""

    SKIPPED = "skipped"
    """Step was skipped during forward recovery."""


class ParallelFailureStrategy(Enum):
    """Strategy for handling parallel step failures"""

    FAIL_FAST = "fail_fast"
    WAIT_ALL = "wait_all"
    FAIL_FAST_WITH_GRACE = "fail_fast_grace"


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

