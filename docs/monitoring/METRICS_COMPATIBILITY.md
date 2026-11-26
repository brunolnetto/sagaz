# Sagaz Metrics Compatibility Matrix

This document maps all Sagaz metrics to their sinks (Grafana dashboards, alerting rules, etc.).

## Names since 2.6.0

Every metric is named `sagaz_*` (#572). Three groups were renamed:

| Before 2.6.0 | Since 2.6.0 |
|---|---|
| `outbox_*` (worker and optimistic publisher) | `sagaz_outbox_*` |
| `consumer_inbox_*` | `sagaz_inbox_*` |
| `saga_*` (`PrometheusMetrics`, default prefix) | `sagaz_saga_*` |

The old names are still emitted, alongside the new ones, while the environment
variable `SAGAZ_METRICS_OLD_NAMES` is on, which is the default. Move your dashboards and
alerts to the new names, then set `SAGAZ_METRICS_OLD_NAMES=0`. Version 3.0 removes the
old names and the variable. A `PrometheusMetrics` created with its own `prefix=` is not
affected.

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
| `sagaz_saga_execution_total` | Counter | `saga_name`, `status` | Sagas Completed, Sagas Failed, Success Rate | SagaHighFailureRate |
| `sagaz_saga_compensations_total` | Counter | `saga_name` | Compensations Executed | - |
| `sagaz_saga_execution_duration_seconds` | Histogram | `saga_name` | - | SagaSlowExecution |
| `sagaz_saga_step_duration_seconds` | Histogram | `saga_name`, `step_name` | Saga Step Duration (p50/p95/p99) | - |
| `sagaz_saga_active_count` | Gauge | `saga_name` | - | SagaHighActiveConcurrency |
| `sagaz_saga_step_executions_total` | Counter | `saga_name`, `step_name`, `status` | - | SagaStepHighFailureRate |
| `sagaz_saga_compensation_failures_total` | Counter | `saga_name`, `step_name` | - | CompensationFailures |

**Source:** `sagaz/monitoring/prometheus.py` (PrometheusMetrics class)

---

## Outbox Worker Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `sagaz_outbox_batch_processed_total` | Counter | `worker_id` | Batch Processing Metrics | - |
| `sagaz_outbox_published_events_total` | Counter | `worker_id`, `event_type` | Event Publish Rate | - |
| `sagaz_outbox_failed_events_total` | Counter | `worker_id`, `event_type` | Event Publish Rate | OutboxHighErrorRate |
| `sagaz_outbox_dead_letter_events_total` | Counter | `worker_id`, `event_type` | Dead Letter Queue | DeadLetterQueueGrowing |
| `sagaz_outbox_retry_attempts_total` | Counter | `worker_id` | Retry Distribution | - |
| `sagaz_outbox_pending_events_total` | Gauge | - | Outbox Pending Events | OutboxHighLag |
| `sagaz_outbox_processing_events_total` | Gauge | `worker_id` | Outbox Pending Events | - |
| `sagaz_outbox_batch_size` | Gauge | `worker_id` | Batch Processing Metrics | - |
| `sagaz_outbox_events_by_state` | Gauge | `state` | Events by State | - |
| `sagaz_outbox_publish_duration_seconds` | Histogram | `worker_id`, `event_type` | Publish Latency Distribution | - |

**Source:** `sagaz/outbox/worker.py`

---

## Optimistic Publisher Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `sagaz_outbox_optimistic_send_attempts_total` | Counter | - | Optimistic Send Success Rate | - |
| `sagaz_outbox_optimistic_send_success_total` | Counter | - | Outbox Event Throughput, Optimistic Success Rate | - |
| `sagaz_outbox_optimistic_send_failures_total` | Counter | `reason` | Outbox Event Throughput | OptimisticSendHighFailureRate |
| `sagaz_outbox_optimistic_send_latency_seconds` | Histogram | - | Optimistic Send Latency (p95) | - |

**Source:** `sagaz/outbox/optimistic_publisher.py`

---

## Consumer Inbox Metrics

| Metric Name | Type | Labels | Dashboard Panel | Alert Rule |
|-------------|------|--------|-----------------|------------|
| `sagaz_inbox_processed_total` | Counter | `consumer_name`, `event_type` | Consumer Inbox Processing | - |
| `sagaz_inbox_duplicates_total` | Counter | `consumer_name`, `event_type` | Consumer Inbox Processing | - |
| `sagaz_inbox_processing_duration_seconds` | Histogram | `consumer_name`, `event_type` | Consumer Processing Duration | - |

**Source:** `sagaz/outbox/consumer_inbox.py`

---

## Dashboard to Metrics Mapping

### grafana-dashboard-main.json

| Panel | Metrics Used | Query |
|-------|--------------|-------|
| Sagas Completed | `sagaz_saga_execution_total` | `sum(sagaz_saga_execution_total{status="completed"})` |
| Sagas Failed | `sagaz_saga_execution_total` | `sum(sagaz_saga_execution_total{status!="completed"})` |
| Saga Success Rate | `sagaz_saga_execution_total` | `sum(sagaz_saga_execution_total{status="completed"}) / sum(sagaz_saga_execution_total)` |
| Compensations Executed | `sagaz_saga_compensations_total` | `sum(sagaz_saga_compensations_total)` |
| Saga Step Duration | `sagaz_saga_step_duration_seconds` | `histogram_quantile(0.50/0.95/0.99, rate(...[5m]))` |
| Outbox Pending Events | `sagaz_outbox_pending_events_total` | `sagaz_outbox_pending_events_total` |
| Outbox Event Throughput | `sagaz_outbox_published_events_total`, `outbox_optimistic_send_*` | `rate(...[5m])` |
| Optimistic Send Success Rate | `outbox_optimistic_send_*` | `sum(success) / sum(attempts)` |
| Optimistic Send Latency | `sagaz_outbox_optimistic_send_latency_seconds` | `histogram_quantile(0.95, ...)` |
| Consumer Inbox Processing | `sagaz_inbox_processed_total`, `sagaz_inbox_duplicates_total` | `rate(...[5m])` |
| Consumer Processing Duration | `sagaz_inbox_processing_duration_seconds` | `histogram_quantile(0.50/0.95/0.99, ...)` |

### grafana-dashboard-outbox.json

| Panel | Metrics Used | Query |
|-------|--------------|-------|
| Outbox Pending Events | `sagaz_outbox_pending_events_total`, `sagaz_outbox_processing_events_total` | Direct gauge values |
| Event Publish Rate | `sagaz_outbox_published_events_total`, `sagaz_outbox_failed_events_total` | `sum(rate(...[5m]))` |
| Publish Success Rate | `sagaz_outbox_published_events_total`, `sagaz_outbox_failed_events_total` | Ratio calculation |
| Dead Letter Queue | `sagaz_outbox_dead_letter_events_total` | `sum(sagaz_outbox_dead_letter_events_total)` |
| Average Publish Latency | `sagaz_outbox_publish_duration_seconds` | `histogram_quantile(0.95, ...)` |
| Publish Latency Distribution | `sagaz_outbox_publish_duration_seconds` | p50/p95/p99 |
| Retry Distribution | `sagaz_outbox_retry_attempts_total` | `sum by (retry_count) (...)` |
| Events by State | `sagaz_outbox_events_by_state` | `sum by (state) (...)` |
| Batch Processing Metrics | `sagaz_outbox_batch_processed_total`, `sagaz_outbox_batch_size` | rate and avg |

---

## Alert Rules (prometheus-alerts.yaml)

| Alert Name | Metric | Condition | Severity |
|------------|--------|-----------|----------|
| `SagaHighFailureRate` | `sagaz_saga_execution_total` | Failure rate > 5% for 10m | warning |
| `OutboxHighLag` | `sagaz_outbox_pending_events_total` | > 5000 events for 10m | warning |
| `OutboxWorkerDown` | `up{job="outbox-worker"}` | No workers for 5m | critical |
| `OutboxHighErrorRate` | `sagaz_outbox_failed_events_total` | > 1% failure rate | warning |
| `OptimisticSendHighFailureRate` | `sagaz_outbox_optimistic_send_failures_total` | > 10% failure rate | warning |
| `DeadLetterQueueGrowing` | `sagaz_outbox_dead_letter_events_total` | Increasing over time | critical |

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
