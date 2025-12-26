"""
Saga monitoring and observability utilities

Provides comprehensive monitoring, logging, and tracing capabilities
for saga pattern implementations.

Quick Start:
    >>> from sagaz.monitoring import setup_saga_logging, is_tracing_available

    # Set up structured logging
    >>> logger = setup_saga_logging(json_format=True)

    # Check if tracing is available
    >>> if is_tracing_available():
    ...     from sagaz.monitoring import setup_tracing
    ...     tracer = setup_tracing("my-service")
"""

from .logging import SagaJsonFormatter, SagaLogger, saga_logger, setup_saga_logging
from .metrics import SagaMetrics
from .tracing import (
    TRACING_AVAILABLE,
    SagaTracer,
    is_tracing_available,
    saga_tracer,
    setup_tracing,
    trace_saga_action,
    trace_saga_compensation,
)

__all__ = [
    "TRACING_AVAILABLE",
    "SagaJsonFormatter",
    # Logging
    "SagaLogger",
    # Metrics
    "SagaMetrics",
    # Tracing
    "SagaTracer",
    "is_tracing_available",
    "saga_logger",
    "saga_tracer",
    "setup_saga_logging",
    "setup_tracing",
    "trace_saga_action",
    "trace_saga_compensation",
]
