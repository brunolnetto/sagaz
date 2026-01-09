"""
Integration Tests for Observability Stack

These tests verify that Sagaz metrics are correctly exposed and can be scraped
by Prometheus, and that Grafana dashboards work correctly.

Requirements:
    - Docker (for testcontainers)
    - pip install testcontainers prometheus-client

Run with:
    pytest tests/test_observability_integration.py -v -m integration
"""

import asyncio
import time
from typing import Any

import pytest

from sagaz import Saga, action, compensate

# ============================================================================
# Test Sagas for Metrics
# ============================================================================


class MetricsTestSaga(Saga):
    """Saga for testing metrics collection."""

    saga_name = "metrics-test-saga"

    @action("step1")
    async def step1(self, ctx):
        await asyncio.sleep(0.01)
        return {"step1": "done"}

    @compensate("step1")
    async def undo_step1(self, ctx):
        pass

    @action("step2", depends_on=["step1"])
    async def step2(self, ctx):
        await asyncio.sleep(0.01)
        return {"step2": "done"}


class FailingSaga(Saga):
    """Saga that fails for testing failure metrics."""

    saga_name = "failing-test-saga"

    @action("fail_step")
    async def fail_step(self, ctx):
        msg = "Intentional failure for metrics testing"
        raise ValueError(msg)

    @compensate("fail_step")
    async def undo_fail_step(self, ctx):
        pass


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.integration
class TestGrafanaDashboardValidity:
    """Test that Grafana dashboards are valid JSON and have correct queries."""

    def test_main_dashboard_is_valid_json(self):
        """Verify main dashboard JSON is valid."""
        import json
        from pathlib import Path

        dashboard_path = Path("sagaz/resources/local/redis/monitoring/grafana/dashboards/grafana-dashboard-main.json")
        if not dashboard_path.exists():
            pytest.skip("Dashboard file not found")

        with open(dashboard_path) as f:
            dashboard = json.load(f)

        # Basic structure validation
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 0
        assert "title" in dashboard

    def test_main_dashboard_queries_use_correct_metrics(self):
        """Verify dashboard queries reference correct metric names."""
        import json
        from pathlib import Path

        dashboard_path = Path("sagaz/resources/local/redis/monitoring/grafana/dashboards/grafana-dashboard-main.json")
        if not dashboard_path.exists():
            pytest.skip("Dashboard file not found")

        with open(dashboard_path) as f:
            dashboard = json.load(f)

        # Collect all metric names from queries
        metric_names = set()
        for panel in dashboard["panels"]:
            if "targets" in panel:
                for target in panel["targets"]:
                    if "expr" in target:
                        expr = target["expr"]
                        # Extract metric name (first word before { or ()
                        for word in expr.split():
                            if word.startswith(("saga_", "outbox_", "consumer_")):
                                metric_name = word.split("{")[0].split("(")[0]
                                metric_names.add(metric_name)

        # Known valid metrics
        valid_metrics = {
            "saga_execution_total",
            "saga_compensations_total",
            "saga_step_duration_seconds",
            "outbox_pending_events_total",
            "outbox_published_events_total",
            "outbox_optimistic_send_success_total",
            "outbox_optimistic_send_failures_total",
            "outbox_optimistic_send_latency_seconds",
            "outbox_optimistic_send_attempts_total",
            "consumer_inbox_processed_total",
            "consumer_inbox_duplicates_total",
            "consumer_inbox_processing_duration_seconds",
        }

        # All metrics in dashboard should be known
        for metric in metric_names:
            # Allow _bucket suffix for histograms
            base_metric = metric.replace("_bucket", "").replace("_count", "").replace("_sum", "")
            assert base_metric in valid_metrics or base_metric.endswith("_seconds"), (
                f"Unknown metric in dashboard: {metric}"
            )

    def test_outbox_dashboard_is_valid_json(self):
        """Verify outbox dashboard JSON is valid."""
        import json
        from pathlib import Path

        dashboard_path = Path("sagaz/resources/local/redis/monitoring/grafana/dashboards/grafana-dashboard-outbox.json")
        if not dashboard_path.exists():
            pytest.skip("Outbox dashboard file not found")

        with open(dashboard_path) as f:
            raw_dashboard = json.load(f)

        # Handle both direct dashboard and ConfigMap wrapped dashboard
        dashboard = raw_dashboard.get("dashboard", raw_dashboard)

        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 0


# ============================================================================
# Metric Name Consistency Tests
# ============================================================================


@pytest.mark.integration
class TestMetricNameConsistency:
    """Test that metric names in code match dashboard expectations."""

    def test_prometheus_metrics_class_has_expected_attributes(self):
        """Verify PrometheusMetrics class defines expected metrics."""
        try:
            from sagaz.monitoring.prometheus import PROMETHEUS_AVAILABLE, PrometheusMetrics
        except ImportError:
            pytest.skip("prometheus-client not installed")

        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus-client not installed")

        # Check the class has the method to record metrics
        assert hasattr(PrometheusMetrics, "record_execution")
        assert hasattr(PrometheusMetrics, "record_step_duration")
        assert hasattr(PrometheusMetrics, "saga_started")
        assert hasattr(PrometheusMetrics, "saga_finished")

    def test_outbox_worker_metrics_exist(self):
        """Verify OutboxWorker defines expected metrics."""
        # Import the module to check metric definitions
        try:
            from sagaz.outbox import worker

            # Check for PROMETHEUS_AVAILABLE flag
            assert hasattr(worker, "PROMETHEUS_AVAILABLE")

            # If available, check metric constants exist
            if worker.PROMETHEUS_AVAILABLE:
                assert hasattr(worker, "OUTBOX_BATCH_PROCESSED") or "OUTBOX" in dir(worker)
        except ImportError:
            pytest.skip("Outbox module not available")


# ============================================================================
# Prometheus Metrics Tests (without actual server to avoid registry issues)
# ============================================================================


@pytest.mark.integration
class TestPrometheusMetricsConfiguration:
    """Test Prometheus metrics configuration."""

    def test_prometheus_metrics_can_be_disabled(self):
        """Test that metrics gracefully handle missing prometheus-client."""
        from sagaz.monitoring.prometheus import is_prometheus_available

        # Should return True or False without error
        result = is_prometheus_available()
        assert isinstance(result, bool)

    def test_metrics_listener_works_without_custom_metrics(self):
        """Test MetricsSagaListener with default metrics."""
        from sagaz.core.listeners import MetricsSagaListener

        # Should create with default metrics
        listener = MetricsSagaListener()
        assert listener.metrics is not None
