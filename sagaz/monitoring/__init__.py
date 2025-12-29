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

    # Enable Prometheus metrics (requires prometheus-client)
    >>> from sagaz.monitoring.prometheus import PrometheusMetrics, start_metrics_server
    >>> start_metrics_server(port=8000)
    >>> metrics = PrometheusMetrics()
"""

from .logging import SagaJsonFormatter, SagaLogger, saga_logger, setup_saga_logging
from .metrics import SagaMetrics
from .prometheus import PrometheusMetrics, is_prometheus_available, start_metrics_server
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
    "PrometheusMetrics",
    "SagaJsonFormatter",
    # Logging
    "SagaLogger",
    # Metrics
    "SagaMetrics",
    # Tracing
    "SagaTracer",
    "is_prometheus_available",
    "is_tracing_available",
    "saga_logger",
    "saga_tracer",
    "setup_saga_logging",
    "setup_tracing",
    "start_metrics_server",
    "trace_saga_action",
    "trace_saga_compensation",
]
