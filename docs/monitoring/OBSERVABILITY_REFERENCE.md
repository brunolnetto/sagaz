# Sagaz Observability Reference

This document provides a comprehensive reference for all metrics, logging, and tracing capabilities available in Sagaz.

## Table of Contents

1. [Prometheus Metrics](#prometheus-metrics)
2. [Logging](#logging)
3. [OpenTelemetry Tracing](#opentelemetry-tracing)
4. [Grafana Dashboards](#grafana-dashboards)
5. [Alerting Rules](#alerting-rules)

---

## Prometheus Metrics

All metrics require `prometheus-client` to be installed (`pip install prometheus-client`).

### Saga Execution Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `saga_execution_total` | Counter | `saga_name`, `status` | Total saga executions by name and status (completed/failed/rolled_back) |
| `saga_compensations_total` | Counter | `saga_name` | Total compensations triggered |
| `saga_execution_duration_seconds` | Histogram | `saga_name` | Saga execution duration (p50, p95, p99) |
| `saga_step_duration_seconds` | Histogram | `saga_name`, `step_name` | Individual step execution durations |
| `saga_active_count` | Gauge | `saga_name` | Currently running sagas |

**Source:** `sagaz/monitoring/prometheus.py` (PrometheusMetrics class)

### Outbox Worker Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `outbox_batch_processed_total` | Counter | `worker_id` | Total batches processed |
| `outbox_published_events_total` | Counter | `worker_id`, `event_type` | Events successfully published to broker |
| `outbox_failed_events_total` | Counter | `worker_id`, `event_type` | Events that failed to publish |
| `outbox_dead_letter_events_total` | Counter | `worker_id`, `event_type` | Events moved to dead letter queue |
| `outbox_retry_attempts_total` | Counter | `worker_id` | Total retry attempts |
| `outbox_pending_events_total` | Gauge | - | Current pending events in outbox |
| `outbox_processing_events_total` | Gauge | `worker_id` | Events currently being processed |
| `outbox_batch_size` | Gauge | `worker_id` | Size of last processed batch |
| `outbox_events_by_state` | Gauge | `state` | Events per state (pending/processing/sent/failed) |
| `outbox_publish_duration_seconds` | Histogram | `worker_id`, `event_type` | Time to publish event to broker |

**Source:** `sagaz/outbox/worker.py`

### Optimistic Publisher Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `outbox_optimistic_send_attempts_total` | Counter | - | Total optimistic send attempts |
| `outbox_optimistic_send_success_total` | Counter | - | Successful optimistic sends |
| `outbox_optimistic_send_failures_total` | Counter | `reason` | Failed optimistic sends by reason (timeout, exception) |
| `outbox_optimistic_send_latency_seconds` | Histogram | - | Latency of optimistic send operation |

**Source:** `sagaz/outbox/optimistic_publisher.py`

### Consumer Inbox Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `consumer_inbox_processed_total` | Counter | `consumer_name`, `event_type` | Total events processed |
| `consumer_inbox_duplicates_total` | Counter | `consumer_name`, `event_type` | Duplicate events skipped |
| `consumer_inbox_processing_duration_seconds` | Histogram | `consumer_name`, `event_type` | Time to process event |

**Source:** `sagaz/outbox/consumer_inbox.py`

---

## Logging

### Structured Logging

Sagaz provides structured JSON logging with correlation IDs:

```python
from sagaz.monitoring import setup_saga_logging

# Configure structured logging
logger = setup_saga_logging(
    level="INFO",
    json_format=True,  # JSON output for log aggregation
    correlation_id=True  # Add correlation IDs
)
```

### Log Format (JSON)

```json
{
  "timestamp": "2024-12-28T19:00:00.000Z",
  "level": "INFO",
  "logger": "sagaz.core",
  "message": "Saga OrderProcessing completed successfully",
  "saga_id": "abc-123",
  "saga_name": "OrderProcessing",
  "duration_ms": 45,
  "correlation_id": "req-xyz-789"
}
```

### Saga Listeners for Logging

```python
from sagaz import Saga, action
from sagaz.listeners import LoggingSagaListener

class OrderSaga(Saga):
    saga_name = "order"
    listeners = [LoggingSagaListener()]  # Auto-log all lifecycle events
    
    @action("step1")
    async def step1(self, ctx):
        return {}
```

**Lifecycle events logged:**
- `[SAGA] Starting: {saga_name} (id={saga_id})`
- `[STEP] Entering: {saga_name}.{step_name}`
- `[STEP] Success: {saga_name}.{step_name}`
- `[STEP] Failed: {saga_name}.{step_name} - {error}`
- `[COMPENSATION] Starting: {saga_name}.{step_name}`
- `[COMPENSATION] Complete: {saga_name}.{step_name}`
- `[SAGA] Completed: {saga_name} (id={saga_id})`
- `[SAGA] Failed: {saga_name} (id={saga_id}) - {error}`

---

## OpenTelemetry Tracing

### Setup

```python
from sagaz.monitoring import setup_tracing, is_tracing_available

if is_tracing_available():
    tracer = setup_tracing(
        service_name="order-service",
        endpoint="http://jaeger:4317"  # OTLP endpoint
    )
```

### Saga Listener for Tracing

```python
from sagaz import Saga, action
from sagaz.listeners import TracingSagaListener

class OrderSaga(Saga):
    saga_name = "order"
    listeners = [TracingSagaListener()]
    
    @action("step1")
    async def step1(self, ctx):
        return {}
```

### Trace Attributes

Each saga span includes:
- `saga.name` - Saga name
- `saga.id` - Unique saga ID
- `saga.status` - Final status (completed/failed/rolled_back)
- `saga.steps.total` - Total number of steps

Each step span includes:
- `step.name` - Step name
- `step.type` - action/compensation
- `step.duration_ms` - Execution time

---

## Grafana Dashboards

### Available Dashboards

| Dashboard | File | Description |
|-----------|------|-------------|
| **Saga Overview** | `grafana-dashboard-main.json` | Saga executions, success rates, step durations |
| **Outbox Pattern** | `grafana-dashboard-outbox.json` | Outbox pending, throughput, latency, DLQ |

### Key Panels

**Saga Overview Dashboard:**
- Sagas Completed / Failed
- Saga Success Rate (%)
- Compensations Executed
- Saga Step Durations (p50, p95, p99)

**Outbox Dashboard:**
- Outbox Pending Events
- Event Publish Rate (events/sec)
- Publish Success Rate (%)
- Dead Letter Queue Count
- Publish Latency Distribution
- Batch Processing Metrics

### Importing Dashboards

```bash
# Copy to Grafana provisioning directory
cp sagaz/resources/k8s/monitoring/grafana-dashboard-*.json \
   /etc/grafana/provisioning/dashboards/
```

---

## Alerting Rules

### Prometheus Alert Rules

Located in: `sagaz/resources/k8s/monitoring/prometheus-alerts.yaml`

| Alert | Condition | Severity |
|-------|-----------|----------|
| `OutboxHighLag` | >5000 pending events for 10min | warning |
| `OutboxWorkerDown` | No healthy workers | critical |
| `OutboxHighErrorRate` | >1% publish failures | warning |
| `SagaHighFailureRate` | >5% saga failures | warning |
| `OptimisticSendHighFailureRate` | >10% optimistic failures | warning |
| `DeadLetterQueueGrowing` | DLQ count increasing | critical |

---

## Quick Start: Enabling All Observability

```python
from sagaz import Saga, action
from sagaz.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    TracingSagaListener,
)
from sagaz.monitoring.prometheus import PrometheusMetrics, start_metrics_server

# 1. Start Prometheus metrics server
start_metrics_server(port=8000)

# 2. Create metrics instance
metrics = PrometheusMetrics()

# 3. Configure saga with all observability
class OrderSaga(Saga):
    saga_name = "order-processing"
    listeners = [
        LoggingSagaListener(),  # Structured logging
        MetricsSagaListener(metrics=metrics),  # Prometheus metrics
        TracingSagaListener(),  # OpenTelemetry tracing
    ]
    
    @action("step1")
    async def step1(self, ctx):
        return {}
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SAGAZ_METRICS_PORT` | Prometheus metrics port | `8000` |
| `SAGAZ_LOG_LEVEL` | Log level | `INFO` |
| `SAGAZ_LOG_JSON` | JSON log format | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry endpoint | - |
| `OTEL_SERVICE_NAME` | Service name for tracing | - |

---

## Development Tracking Checklist

Use this checklist to verify observability is working:

### Metrics
- [ ] Prometheus server accessible at `/metrics` endpoint
- [ ] `saga_execution_total` incrementing on saga runs
- [ ] `saga_step_duration_seconds` showing latency buckets
- [ ] `outbox_published_events_total` tracking event publishing
- [ ] Grafana dashboards displaying data

### Logging
- [ ] JSON logs parsing correctly in log aggregator
- [ ] Correlation IDs present in logs
- [ ] All saga lifecycle events logged

### Tracing
- [ ] Traces appearing in Jaeger/Zipkin/Tempo
- [ ] Spans correctly nested (saga -> steps)
- [ ] Step durations matching metrics

---

*Last updated: December 2024*
