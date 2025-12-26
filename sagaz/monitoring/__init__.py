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
    # Metrics
    "SagaMetrics",

    # Logging
    "SagaLogger",
    "SagaJsonFormatter",
    "setup_saga_logging",
    "saga_logger",

    # Tracing
    "SagaTracer",
    "trace_saga_action",
    "trace_saga_compensation",
    "setup_tracing",
    "saga_tracer",
    "is_tracing_available",
    "TRACING_AVAILABLE",
]
