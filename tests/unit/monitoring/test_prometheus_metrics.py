"""
Tests for Prometheus metrics coverage.

These tests cover the PrometheusMetrics class and related functionality.
"""

import pytest

from sagaz.monitoring.prometheus import (
    PROMETHEUS_AVAILABLE,
    PrometheusMetrics,
    is_prometheus_available,
    start_metrics_server,
)
from sagaz.types import SagaStatus


@pytest.fixture
def fresh_metrics():
    """Create fresh PrometheusMetrics instance for each test."""
    # Note: Prometheus uses global registry, so metrics accumulate across tests
    # We use unique prefixes to avoid conflicts
    import uuid

    prefix = f"test_saga_{uuid.uuid4().hex[:8]}"
    return PrometheusMetrics(prefix=prefix)


class TestPrometheusMetrics:
    """Tests for PrometheusMetrics class."""

    def test_prometheus_is_available(self):
        """Verify prometheus_client is installed in test environment."""
        assert PROMETHEUS_AVAILABLE is True
        assert is_prometheus_available() is True

    def test_metrics_initialization(self, fresh_metrics):
        """Test metrics are created on initialization."""
        assert fresh_metrics._enabled is True
        assert fresh_metrics._execution_total is not None
        assert fresh_metrics._compensations_total is not None
        assert fresh_metrics._execution_duration is not None
        assert fresh_metrics._step_duration is not None
        assert fresh_metrics._active_count is not None

    def test_record_execution_completed(self, fresh_metrics):
        """Test recording a completed saga execution."""
        fresh_metrics.record_execution(
            saga_name="TestSaga",
            status=SagaStatus.COMPLETED,
            duration=1.5,
        )
        # Should not raise - metrics recorded

    def test_record_execution_failed(self, fresh_metrics):
        """Test recording a failed saga execution (triggers compensation counter)."""
        fresh_metrics.record_execution(
            saga_name="TestSaga",
            status=SagaStatus.FAILED,
            duration=0.5,
        )
        # Should increment compensations_total

    def test_record_execution_rolled_back(self, fresh_metrics):
        """Test recording a rolled_back saga execution."""
        fresh_metrics.record_execution(
            saga_name="TestSaga",
            status=SagaStatus.ROLLED_BACK,
            duration=2.0,
        )
        # Should increment compensations_total

    def test_record_step_duration(self, fresh_metrics):
        """Test recording step duration."""
        fresh_metrics.record_step_duration(
            saga_name="TestSaga",
            step_name="validate_order",
            duration=0.1,
        )
        # Should not raise

    def test_saga_started(self, fresh_metrics):
        """Test recording saga start."""
        fresh_metrics.saga_started(saga_name="TestSaga")
        # Should increment active_count

    def test_saga_finished(self, fresh_metrics):
        """Test recording saga finish."""
        fresh_metrics.saga_started(saga_name="TestSaga")
        fresh_metrics.saga_finished(saga_name="TestSaga")
        # Should decrement active_count

    def test_saga_lifecycle_tracking(self, fresh_metrics):
        """Test full saga lifecycle: start -> record -> finish."""
        saga_name = "OrderProcessingSaga"

        # Start
        fresh_metrics.saga_started(saga_name)

        # Record steps
        fresh_metrics.record_step_duration(saga_name, "validate", 0.1)
        fresh_metrics.record_step_duration(saga_name, "process", 0.5)

        # Complete
        fresh_metrics.record_execution(saga_name, SagaStatus.COMPLETED, 0.6)
        fresh_metrics.saga_finished(saga_name)
        # Should not raise

    def test_record_execution_with_string_status(self, fresh_metrics):
        """Test recording execution with string status (edge case)."""
        # Status might be passed as string in some contexts
        fresh_metrics.record_execution(
            saga_name="TestSaga",
            status="completed",  # type: ignore - testing edge case
            duration=1.0,
        )


class TestStartMetricsServer:
    """Tests for start_metrics_server function."""

    def test_start_metrics_server_creates_server(self):
        """Test that start_metrics_server calls prometheus start_http_server."""
        from unittest.mock import patch

        with patch("sagaz.monitoring.prometheus.start_http_server") as mock_start:
            start_metrics_server(port=9999, addr="127.0.0.1")
            mock_start.assert_called_once_with(9999, "127.0.0.1")

    def test_start_metrics_server_default_args(self):
        """Test start_metrics_server with default arguments."""
        from unittest.mock import patch

        with patch("sagaz.monitoring.prometheus.start_http_server") as mock_start:
            start_metrics_server()
            mock_start.assert_called_once_with(8000, "0.0.0.0")


class TestMetricsDisabled:
    """Test behavior when metrics are disabled."""

    def test_methods_are_noop_when_disabled(self):
        """Test that all methods are no-op when prometheus not available."""
        from unittest.mock import patch

        # Temporarily make prometheus unavailable
        with patch("sagaz.monitoring.prometheus.PROMETHEUS_AVAILABLE", False):
            # Import and recreate metrics
            from sagaz.monitoring.prometheus import PrometheusMetrics as PM

            metrics = PM()

            # All these should not raise
            metrics.record_execution("Test", SagaStatus.COMPLETED, 1.0)
            metrics.record_step_duration("Test", "step", 0.1)
            metrics.saga_started("Test")
            metrics.saga_finished("Test")

    def test_start_server_logs_error_when_unavailable(self, caplog):
        """Test start_metrics_server logs error when prometheus unavailable."""
        import logging
        from unittest.mock import patch

        with patch("sagaz.monitoring.prometheus.PROMETHEUS_AVAILABLE", False):
            from sagaz.monitoring.prometheus import start_metrics_server

            with caplog.at_level(logging.ERROR):
                start_metrics_server()

            assert "Cannot start metrics server" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
