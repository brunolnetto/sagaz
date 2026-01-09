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
