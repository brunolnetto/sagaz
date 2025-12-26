# ============================================
# FILE: saga/types.py
# ============================================

"""
All type definitions, enums, and dataclasses
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SagaStatus(Enum):
    """Overall saga status"""

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class SagaStepStatus(Enum):
    """Status of individual saga step"""

    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class ParallelFailureStrategy(Enum):
    """Strategy for handling parallel step failures"""

    FAIL_FAST = "fail_fast"
    WAIT_ALL = "wait_all"
    FAIL_FAST_WITH_GRACE = "fail_fast_grace"


@dataclass
class SagaResult:
    """Result of saga execution"""

    success: bool
    saga_name: str
    status: SagaStatus
    completed_steps: int
    total_steps: int
    error: Exception | None = None
    execution_time: float = 0.0
    context: Any = None
    compensation_errors: list[Exception] = field(default_factory=list)

    @property
    def is_completed(self) -> bool:
        return self.status == SagaStatus.COMPLETED

    @property
    def is_rolled_back(self) -> bool:
        return self.status == SagaStatus.ROLLED_BACK
