# ============================================
# FILE: saga/exceptions.py
# ============================================

"""
All saga-related exceptions
"""


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


class MissingDependencyError(SagaError):
    """
    Raised when an optional dependency is not installed.

    This exception provides clear installation instructions to help users
    quickly resolve missing package issues.
    """

    INSTALL_COMMANDS = {
        "redis": "pip install redis",
        "asyncpg": "pip install asyncpg",
        "opentelemetry": "pip install opentelemetry-api opentelemetry-sdk",
        "opentelemetry-otlp": "pip install opentelemetry-exporter-otlp-proto-grpc",
    }

    def __init__(self, package: str, feature: str | None = None):
        self.package = package
        self.feature = feature

        install_cmd = self.INSTALL_COMMANDS.get(package, f"pip install {package}")

        if feature:
            message = (
                f"\n╔══════════════════════════════════════════════════════════════╗\n"
                f"║  Missing Dependency: {package:<40} ║\n"
                f"╠══════════════════════════════════════════════════════════════╣\n"
                f"║  Required for: {feature:<45} ║\n"
                f"║  Install with: {install_cmd:<45} ║\n"
                f"╚══════════════════════════════════════════════════════════════╝"
            )
        else:
            message = (
                f"\n╔══════════════════════════════════════════════════════════════╗\n"
                f"║  Missing Dependency: {package:<40} ║\n"
                f"╠══════════════════════════════════════════════════════════════╣\n"
                f"║  Install with: {install_cmd:<45} ║\n"
                f"╚══════════════════════════════════════════════════════════════╝"
            )

        super().__init__(message)


class IdempotencyKeyRequiredError(SagaError):
    """
    Raised when a high-value operation lacks an idempotency key.

    This exception enforces safe-by-default behavior for financial
    and high-value operations, preventing duplicate execution.
    """

    def __init__(self, saga_name: str, source: str, detected_fields: list[str]):
        self.saga_name = saga_name
        self.source = source
        self.detected_fields = detected_fields

        fields_str = ", ".join(detected_fields)
        message = (
            f"\n╔══════════════════════════════════════════════════════════════╗\n"
            f"║  IDEMPOTENCY KEY REQUIRED                                    ║\n"
            f"╠══════════════════════════════════════════════════════════════╣\n"
            f"║  Saga: {saga_name:<53} ║\n"
            f"║  Trigger Source: {source:<45} ║\n"
            f"║                                                              ║\n"
            f"║  High-value operation detected with fields:                 ║\n"
            f"║  {fields_str:<59} ║\n"
            f"║                                                              ║\n"
            f"║  To prevent duplicate execution, add an idempotency key:    ║\n"
            f"║                                                              ║\n"
            f"║  @trigger(                                                   ║\n"
            f"║      source='{source}',                                        ║\n"
            f"║      idempotency_key='<unique_field>'  # e.g., 'order_id'   ║\n"
            f"║  )                                                           ║\n"
            f"║                                                              ║\n"
            f"║  Or use a callable for composite keys:                      ║\n"
            '║  idempotency_key=lambda p: f\'{p["user_id"]}-{p["order_id"]}\'  ║\n'
            f"║                                                              ║\n"
            f"╚══════════════════════════════════════════════════════════════╝"
        )

        super().__init__(message)
