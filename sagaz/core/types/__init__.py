"""
Type definitions, enums, and dataclasses for Saga execution.

Extended in v1.3.0 with pivot/irreversible step support:
- PARTIALLY_COMMITTED and FORWARD_RECOVERY saga statuses
- Pivot-aware fields in SagaResult
"""

from sagaz.core.types._enums import ParallelFailureStrategy, SagaStatus, SagaStepStatus
from sagaz.core.types._result import SagaResult

__all__ = [
    "ParallelFailureStrategy",
    "SagaResult",
    "SagaStatus",
    "SagaStepStatus",
]
