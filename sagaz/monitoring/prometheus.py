# ============================================
# FILE: sagaz/monitoring/prometheus.py
# ============================================

"""
Prometheus metrics integration for Sagaz.

Provides Prometheus-native metrics collection for saga executions,
compatible with the Grafana dashboards.

Quick Start:
    >>> from sagaz.monitoring.prometheus import PrometheusMetrics, start_metrics_server
    >>>
    >>> # Start the metrics server
    >>> start_metrics_server(port=8000)
    >>>
    >>> # Create metrics collector
    >>> metrics = PrometheusMetrics()
    >>>
    >>> # Use with MetricsSagaListener
    >>> from sagaz.core.listeners import MetricsSagaListener
    >>> class OrderSaga(Saga):
    ...     listeners = [MetricsSagaListener(metrics=metrics)]

Requirements:
    pip install prometheus-client
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from sagaz.core.types import SagaStatus

# Check if prometheus_client is installed
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    PROMETHEUS_AVAILABLE = False
    Counter: Any = None  # type: ignore[no-redef]
    Gauge: Any = None  # type: ignore[no-redef]
    Histogram: Any = None  # type: ignore[no-redef]
    start_http_server: Any = None  # type: ignore[no-redef]


logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """
    Prometheus-compatible metrics collector for Sagaz.

    Exposes the following metrics:
        - saga_execution_total: Counter of saga executions by name and status
        - saga_compensations_total: Counter of saga compensations
        - saga_execution_duration_seconds: Histogram of saga durations
        - saga_step_duration_seconds: Histogram of step durations
        - saga_active_count: Gauge of currently running sagas

    Example:
        >>> from sagaz.monitoring.prometheus import PrometheusMetrics
        >>> from sagaz.core.listeners import MetricsSagaListener
        >>>
        >>> metrics = PrometheusMetrics()
        >>>
        >>> class OrderSaga(Saga):
        ...     listeners = [MetricsSagaListener(metrics=metrics)]
    """

    def __init__(self, prefix: str = "saga"):
        """
        Initialize Prometheus metrics.

        Args:
            prefix: Metric name prefix (default: "saga")
        """
        if not PROMETHEUS_AVAILABLE:
            logger.warning(
                "prometheus-client not installed. Metrics will not be collected. "
                "Install with: pip install prometheus-client"
            )
            self._enabled = False
            return

        self._enabled = True
        self._prefix = prefix

        # Total saga executions by status
        self._execution_total = Counter(
            f"{prefix}_execution_total",
            "Total saga executions",
            ["saga_name", "status"],
        )

        # Total compensations triggered
        self._compensations_total = Counter(
            f"{prefix}_compensations_total",
            "Total saga compensations triggered",
            ["saga_name"],
        )

        # Saga execution duration
        self._execution_duration = Histogram(
            f"{prefix}_execution_duration_seconds",
            "Saga execution duration in seconds",
            ["saga_name"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        )

        # Step execution duration
        self._step_duration = Histogram(
            f"{prefix}_step_duration_seconds",
            "Saga step execution duration in seconds",
            ["saga_name", "step_name"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
        )

        # Currently active sagas
        self._active_count = Gauge(
            f"{prefix}_active_count",
            "Number of currently running sagas",
            ["saga_name"],
        )

    def record_execution(self, saga_name: str, status: "SagaStatus", duration: float) -> None:
        """
        Record a saga execution.

        Called by MetricsSagaListener when a saga completes.

        Args:
            saga_name: Name of the saga
            status: Final status of the saga
            duration: Execution duration in seconds
        """
        if not self._enabled:
            return

        status_str = status.value if hasattr(status, "value") else str(status)
        self._execution_total.labels(saga_name=saga_name, status=status_str).inc()
        self._execution_duration.labels(saga_name=saga_name).observe(duration)

        # Track compensations for failed/rolled_back sagas
        if status_str in ("failed", "rolled_back"):
            self._compensations_total.labels(saga_name=saga_name).inc()

    def record_step_duration(self, saga_name: str, step_name: str, duration: float) -> None:
        """
        Record a step execution duration.

        Args:
            saga_name: Name of the saga
            step_name: Name of the step
            duration: Execution duration in seconds
        """
        if not self._enabled:
            return

        self._step_duration.labels(saga_name=saga_name, step_name=step_name).observe(duration)

    def saga_started(self, saga_name: str) -> None:
        """
        Record that a saga has started.

        Args:
            saga_name: Name of the saga
        """
        if not self._enabled:
            return

        self._active_count.labels(saga_name=saga_name).inc()

    def saga_finished(self, saga_name: str) -> None:
        """
        Record that a saga has finished.

        Args:
            saga_name: Name of the saga
        """
        if not self._enabled:
            return

        self._active_count.labels(saga_name=saga_name).dec()


def start_metrics_server(port: int = 8000, addr: str = "0.0.0.0") -> None:
    """
    Start a Prometheus HTTP metrics server.

    Args:
        port: Port to listen on (default: 8000)
        addr: Address to bind to (default: 0.0.0.0 for all interfaces)

    Example:
        >>> from sagaz.monitoring.prometheus import start_metrics_server
        >>> start_metrics_server(port=8000)
        >>> # Metrics available at http://localhost:8000/metrics
    """
    if not PROMETHEUS_AVAILABLE:
        logger.error(
            "Cannot start metrics server: prometheus-client not installed. "
            "Install with: pip install prometheus-client"
        )
        return

    start_http_server(port, addr)
    logger.info(f"Prometheus metrics server started on port {port}")


def is_prometheus_available() -> bool:
    """Check if prometheus-client is installed."""
    return PROMETHEUS_AVAILABLE
