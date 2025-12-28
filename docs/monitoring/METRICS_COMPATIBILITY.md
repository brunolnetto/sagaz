# Sagaz Metrics Compatibility Matrix

This document maps all Sagaz metrics to their sinks (Grafana dashboards, alerting rules, etc.).

## Metrics Overview

| Component | # of Metrics | Dashboard | Alerts |
|-----------|-------------|-----------|--------|
| Saga Execution | 5 | `grafana-dashboard-main.json` | Yes |
| Outbox Worker | 10 | `grafana-dashboard-outbox.json` | Yes |
| Optimistic Publisher | 4 | `grafana-dashboard-main.json` | Yes |
| Consumer Inbox | 3 | `grafana-dashboard-main.json` | No |

---

## Saga Execution Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `saga_execution_total` | Counter | `saga_name`, `status` | Sagas Completed, Sagas Failed, Success Rate | SagaHighFailureRate |
| `saga_compensations_total` | Counter | `saga_name` | Compensations Executed | - |
| `saga_execution_duration_seconds` | Histogram | `saga_name` | - | SagaSlowExecution |
| `saga_step_duration_seconds` | Histogram | `saga_name`, `step_name` | Saga Step Duration (p50/p95/p99) | - |
| `saga_active_count` | Gauge | `saga_name` | - | - |

**Source:** `sagaz/monitoring/prometheus.py` (PrometheusMetrics class)

---

## Outbox Worker Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `outbox_batch_processed_total` | Counter | `worker_id` | Batch Processing Metrics | - |
| `outbox_published_events_total` | Counter | `worker_id`, `event_type` | Event Publish Rate | - |
| `outbox_failed_events_total` | Counter | `worker_id`, `event_type` | Event Publish Rate | OutboxHighErrorRate |
| `outbox_dead_letter_events_total` | Counter | `worker_id`, `event_type` | Dead Letter Queue | DeadLetterQueueGrowing |
| `outbox_retry_attempts_total` | Counter | `worker_id` | Retry Distribution | - |
| `outbox_pending_events_total` | Gauge | - | Outbox Pending Events | OutboxHighLag |
| `outbox_processing_events_total` | Gauge | `worker_id` | Outbox Pending Events | - |
| `outbox_batch_size` | Gauge | `worker_id` | Batch Processing Metrics | - |
| `outbox_events_by_state` | Gauge | `state` | Events by State | - |
| `outbox_publish_duration_seconds` | Histogram | `worker_id`, `event_type` | Publish Latency Distribution | - |

**Source:** `sagaz/outbox/worker.py`

---

## Optimistic Publisher Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `outbox_optimistic_send_attempts_total` | Counter | - | Optimistic Send Success Rate | - |
| `outbox_optimistic_send_success_total` | Counter | - | Outbox Event Throughput, Optimistic Success Rate | - |
| `outbox_optimistic_send_failures_total` | Counter | `reason` | Outbox Event Throughput | OptimisticSendHighFailureRate |
| `outbox_optimistic_send_latency_seconds` | Histogram | - | Optimistic Send Latency (p95) | - |

**Source:** `sagaz/outbox/optimistic_publisher.py`

---

## Consumer Inbox Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `consumer_inbox_processed_total` | Counter | `consumer_name`, `event_type` | Consumer Inbox Processing | - |
| `consumer_inbox_duplicates_total` | Counter | `consumer_name`, `event_type` | Consumer Inbox Processing | - |
| `consumer_inbox_processing_duration_seconds` | Histogram | `consumer_name`, `event_type` | Consumer Processing Duration | - |

**Source:** `sagaz/outbox/consumer_inbox.py`

---

## Dashboard to Metrics Mapping

### grafana-dashboard-main.json

| Panel | Metrics Used | Query |
|-------|--------------|-------|
| Sagas Completed | `saga_execution_total` | `sum(saga_execution_total{status="completed"})` |
| Sagas Failed | `saga_execution_total` | `sum(saga_execution_total{status="failed"})` |
| Saga Success Rate | `saga_execution_total` | `sum(saga_execution_total{status="completed"}) / sum(saga_execution_total)` |
| Compensations Executed | `saga_compensations_total` | `sum(saga_compensations_total)` |
| Saga Step Duration | `saga_step_duration_seconds` | `histogram_quantile(0.50/0.95/0.99, rate(...[5m]))` |
| Outbox Pending Events | `outbox_pending_events_total` | `outbox_pending_events_total` |
| Outbox Event Throughput | `outbox_published_events_total`, `outbox_optimistic_send_*` | `rate(...[5m])` |
| Optimistic Send Success Rate | `outbox_optimistic_send_*` | `sum(success) / sum(attempts)` |
| Optimistic Send Latency | `outbox_optimistic_send_latency_seconds` | `histogram_quantile(0.95, ...)` |
| Consumer Inbox Processing | `consumer_inbox_processed_total`, `consumer_inbox_duplicates_total` | `rate(...[5m])` |
| Consumer Processing Duration | `consumer_inbox_processing_duration_seconds` | `histogram_quantile(0.50/0.95/0.99, ...)` |

### grafana-dashboard-outbox.json

| Panel | Metrics Used | Query |
|-------|--------------|-------|
| Outbox Pending Events | `outbox_pending_events_total`, `outbox_processing_events_total` | Direct gauge values |
| Event Publish Rate | `outbox_published_events_total`, `outbox_failed_events_total` | `sum(rate(...[5m]))` |
| Publish Success Rate | `outbox_published_events_total`, `outbox_failed_events_total` | Ratio calculation |
| Dead Letter Queue | `outbox_dead_letter_events_total` | `sum(outbox_dead_letter_events_total)` |
| Average Publish Latency | `outbox_publish_duration_seconds` | `histogram_quantile(0.95, ...)` |
| Publish Latency Distribution | `outbox_publish_duration_seconds` | p50/p95/p99 |
| Retry Distribution | `outbox_retry_attempts_total` | `sum by (retry_count) (...)` |
| Events by State | `outbox_events_by_state` | `sum by (state) (...)` |
| Batch Processing Metrics | `outbox_batch_processed_total`, `outbox_batch_size` | rate and avg |

---

## Alert Rules (prometheus-alerts.yaml)

| Alert Name | Metric | Condition | Severity |
|------------|--------|-----------|----------|
| `SagaHighFailureRate` | `saga_execution_total` | Failure rate > 5% for 10m | warning |
| `OutboxHighLag` | `outbox_pending_events_total` | > 5000 events for 10m | warning |
| `OutboxWorkerDown` | `up{job="outbox-worker"}` | No workers for 5m | critical |
| `OutboxHighErrorRate` | `outbox_failed_events_total` | > 1% failure rate | warning |
| `OptimisticSendHighFailureRate` | `outbox_optimistic_send_failures_total` | > 10% failure rate | warning |
| `DeadLetterQueueGrowing` | `outbox_dead_letter_events_total` | Increasing over time | critical |

---

## Log Sinks

### Structured JSON Logging

All Sagaz components output structured JSON logs compatible with:
- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Loki** (Grafana's log aggregation)
- **CloudWatch Logs**
- **Datadog Logs**

Log fields include:
- `timestamp` - ISO 8601 format
- `level` - INFO, WARNING, ERROR
- `logger` - Component name (sagaz.core, sagaz.outbox, etc.)
- `message` - Log message
- `saga_id` - Saga execution ID (for correlation)
- `saga_name` - Saga name
- `step_name` - Step name (when applicable)
- `duration_ms` - Operation duration
- `correlation_id` - Request correlation ID

### Example Loki Query

```logql
{job="sagaz"} |= "saga_id" | json | saga_name="order-processing"
```

---

## OpenTelemetry Tracing Sinks

Compatible with:
- **Jaeger**
- **Zipkin**
- **Tempo** (Grafana)
- **Honeycomb**
- **Datadog APM**

Export endpoint: `OTEL_EXPORTER_OTLP_ENDPOINT`

---

*Last updated: December 2024*
