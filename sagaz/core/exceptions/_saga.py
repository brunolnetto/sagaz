"""Core saga exception hierarchy."""


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
