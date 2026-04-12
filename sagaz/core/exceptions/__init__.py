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


class SagaError(Exception):
    """Base saga error"""


class SagaStepError(SagaError):
    """Error executing saga step"""


class SagaCompensationError(SagaError):
    """Error executing compensation"""


class SagaTimeoutError(SagaError):
    """Saga step timeout"""


class SagaExecutionError(SagaError):
    """Error during saga execution"""


class SagaDependencyError(SagaError):
    """Invalid dependency configuration"""


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
