"""
All saga-related exceptions.

Provides comprehensive exception hierarchy for saga processing,
dependency management, and idempotency control.
"""

from sagaz.core.exceptions._dependency import MissingDependencyError
from sagaz.core.exceptions._idempotency import (
    IdempotencyKeyMissingInPayloadError,
    IdempotencyKeyRequiredError,
)
from sagaz.core.exceptions._saga import (
    SagaCompensationError,
    SagaDependencyError,
    SagaError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)

__all__ = [
    "IdempotencyKeyMissingInPayloadError",
    "IdempotencyKeyRequiredError",
    "MissingDependencyError",
    "SagaCompensationError",
    "SagaDependencyError",
    "SagaError",
    "SagaExecutionError",
    "SagaStepError",
    "SagaTimeoutError",
]
