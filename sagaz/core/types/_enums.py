"""Saga status and strategy enums."""

from enum import Enum


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
