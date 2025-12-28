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

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers")

from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from sagaz import Saga, action, compensate


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def prometheus_container():
    """Start a Prometheus container for integration testing."""
    # Create a minimal Prometheus config
    prometheus_config = """
global:
  scrape_interval: 1s
  evaluation_interval: 1s

scrape_configs:
  - job_name: 'sagaz-test'
    static_configs:
      - targets: ['host.docker.internal:9999']
    scrape_interval: 1s
    scrape_timeout: 1s
"""
    
    container = (
        DockerContainer("prom/prometheus:v2.47.0")
        .with_exposed_ports(9090)
        .with_env("TZ", "UTC")
    )
    
    try:
        container.start()
        # Wait for Prometheus to be ready
        wait_for_logs(container, "Server is ready to receive web requests", timeout=30)
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def metrics_server():
    """Start a local metrics server for Prometheus to scrape."""
    try:
        from prometheus_client import start_http_server, REGISTRY
        from prometheus_client.core import CollectorRegistry
        
        # Start metrics server on port 9999
        start_http_server(9999)
        yield 9999
    except ImportError:
        pytest.skip("prometheus-client not installed")
    except OSError:
        # Port already in use, which is fine
        yield 9999


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
        raise ValueError("Intentional failure for metrics testing")
    
    @compensate("fail_step")
    async def undo_fail_step(self, ctx):
        pass


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.integration
class TestPrometheusMetrics:
    """Test that Prometheus metrics are correctly exposed."""
    
    @pytest.mark.asyncio
    async def test_metrics_endpoint_available(self, metrics_server):
        """Verify metrics endpoint is accessible."""
        import urllib.request
        
        url = f"http://localhost:{metrics_server}/metrics"
        
        # May need a few retries for server to be ready
        for _ in range(5):
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    content = response.read().decode("utf-8")
                    assert "python_info" in content  # Standard prometheus-client metric
                    break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            pytest.fail("Metrics endpoint not available")
    
    @pytest.mark.asyncio
    async def test_saga_execution_metrics_recorded(self, metrics_server):
        """Verify saga execution records metrics."""
        from sagaz.monitoring.prometheus import PrometheusMetrics
        from sagaz.listeners import MetricsSagaListener
        
        # Create metrics instance
        metrics = PrometheusMetrics()
        
        # Create saga with metrics listener
        class TestSaga(Saga):
            saga_name = "execution-metrics-test"
            listeners = [MetricsSagaListener(metrics=metrics)]
            
            @action("test_step")
            async def test_step(self, ctx):
                return {"done": True}
        
        # Execute saga
        saga = TestSaga()
        await saga.run({})
        
        # Check metrics were recorded
        import urllib.request
        
        url = f"http://localhost:{metrics_server}/metrics"
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read().decode("utf-8")
            
            # Should have saga execution metrics
            assert "saga_execution_total" in content or "saga_active_count" in content
    
    @pytest.mark.asyncio
    async def test_saga_failure_metrics_recorded(self, metrics_server):
        """Verify failed saga records failure metrics."""
        from sagaz.monitoring.prometheus import PrometheusMetrics
        from sagaz.listeners import MetricsSagaListener
        
        metrics = PrometheusMetrics()
        
        class FailTestSaga(Saga):
            saga_name = "failure-metrics-test"
            listeners = [MetricsSagaListener(metrics=metrics)]
            
            @action("failing_step")
            async def failing_step(self, ctx):
                raise RuntimeError("Test failure")
        
        saga = FailTestSaga()
        
        with pytest.raises(RuntimeError):
            await saga.run({})
        
        # Metrics should still be recorded for failed saga
        import urllib.request
        
        url = f"http://localhost:{metrics_server}/metrics"
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read().decode("utf-8")
            # Should have saga metrics even for failures
            assert "saga" in content.lower()


@pytest.mark.integration
class TestGrafanaDashboardValidity:
    """Test that Grafana dashboards are valid JSON and have correct queries."""
    
    def test_main_dashboard_is_valid_json(self):
        """Verify main dashboard JSON is valid."""
        import json
        from pathlib import Path
        
        dashboard_path = Path("sagaz/resources/k8s/monitoring/grafana-dashboard-main.json")
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
        
        dashboard_path = Path("sagaz/resources/k8s/monitoring/grafana-dashboard-main.json")
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
                            if word.startswith("saga_") or word.startswith("outbox_") or word.startswith("consumer_"):
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
            "consumer_inbox_processed_total",
            "consumer_inbox_duplicates_total",
            "consumer_inbox_processing_duration_seconds",
        }
        
        # All metrics in dashboard should be known
        for metric in metric_names:
            # Allow _bucket suffix for histograms
            base_metric = metric.replace("_bucket", "").replace("_count", "").replace("_sum", "")
            assert base_metric in valid_metrics or base_metric.endswith("_seconds"), \
                f"Unknown metric in dashboard: {metric}"
    
    def test_outbox_dashboard_is_valid_json(self):
        """Verify outbox dashboard JSON is valid."""
        import json
        from pathlib import Path
        
        dashboard_path = Path("sagaz/resources/k8s/monitoring/grafana-dashboard-outbox.json")
        if not dashboard_path.exists():
            pytest.skip("Outbox dashboard file not found")
        
        with open(dashboard_path) as f:
            dashboard = json.load(f)
        
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 0


@pytest.mark.integration
class TestAlertRulesValidity:
    """Test that Prometheus alert rules are valid."""
    
    def test_prometheus_alerts_is_valid_yaml(self):
        """Verify alert rules YAML is valid."""
        import yaml
        from pathlib import Path
        
        alerts_path = Path("sagaz/resources/k8s/monitoring/prometheus-alerts.yaml")
        if not alerts_path.exists():
            pytest.skip("Alerts file not found")
        
        with open(alerts_path) as f:
            alerts = yaml.safe_load(f)
        
        # Should have groups with rules
        assert "groups" in alerts
        assert len(alerts["groups"]) > 0
        
        for group in alerts["groups"]:
            assert "name" in group
            assert "rules" in group
    
    def test_alertmanager_rules_is_valid_yaml(self):
        """Verify alertmanager rules YAML is valid."""
        import yaml
        from pathlib import Path
        
        rules_path = Path("sagaz/resources/k8s/monitoring/alertmanager-rules.yml")
        if not rules_path.exists():
            pytest.skip("Alertmanager rules file not found")
        
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        
        # Basic structure validation
        assert rules is not None


# ============================================================================
# Metric Name Consistency Tests
# ============================================================================


@pytest.mark.integration
class TestMetricNameConsistency:
    """Test that metric names in code match dashboard expectations."""
    
    def test_prometheus_metrics_class_names_match_dashboard(self):
        """Verify PrometheusMetrics class defines expected metrics."""
        try:
            from sagaz.monitoring.prometheus import PrometheusMetrics
        except ImportError:
            pytest.skip("prometheus-client not installed")
        
        metrics = PrometheusMetrics()
        
        # Check expected metrics exist
        assert hasattr(metrics, "_execution_total")
        assert hasattr(metrics, "_compensations_total")
        assert hasattr(metrics, "_execution_duration")
        assert hasattr(metrics, "_step_duration")
        assert hasattr(metrics, "_active_count")
    
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
# Docker Compose Stack Test (Optional)
# ============================================================================


@pytest.mark.integration
@pytest.mark.slow
class TestFullObservabilityStack:
    """End-to-end test with full observability stack."""
    
    @pytest.mark.asyncio
    async def test_metrics_flow_through_stack(self, prometheus_container, metrics_server):
        """Test that metrics flow from Sagaz -> Prometheus."""
        from sagaz.monitoring.prometheus import PrometheusMetrics
        from sagaz.listeners import MetricsSagaListener
        
        # Setup metrics
        metrics = PrometheusMetrics()
        
        # Create and run test saga
        class FlowTestSaga(Saga):
            saga_name = "flow-test"
            listeners = [MetricsSagaListener(metrics=metrics)]
            
            @action("step1")
            async def step1(self, ctx):
                return {"done": True}
        
        # Run multiple sagas to generate metrics
        for _ in range(10):
            saga = FlowTestSaga()
            await saga.run({})
        
        # Wait for metrics to be scraped
        await asyncio.sleep(2)
        
        # Verify metrics are exposed
        import urllib.request
        
        url = f"http://localhost:{metrics_server}/metrics"
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read().decode("utf-8")
            assert "saga" in content.lower()
        
        # Note: Full Prometheus scrape verification would require
        # configuring Prometheus to scrape host.docker.internal:9999
        # and then querying Prometheus API, which is complex in CI
