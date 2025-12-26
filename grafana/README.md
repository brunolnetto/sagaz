# Grafana Dashboards for Sagaz

Production-ready Grafana dashboards for monitoring the Sagaz saga pattern library.

## Available Dashboards

### 1. Sagaz - Saga Pattern Monitoring (`sagaz-dashboard.json`)

Comprehensive dashboard for monitoring saga executions, outbox pattern, and consumer inbox.

**Panels include:**

#### Saga Overview
- **Sagas Completed** - Total successful saga executions
- **Sagas Failed** - Total failed saga executions (with rollback)
- **Saga Success Rate** - Percentage of successful sagas
- **Compensations Executed** - Number of compensation actions triggered
- **Saga Step Duration** - p50/p95/p99 latency of individual steps

#### Outbox Pattern
- **Outbox Pending Events** - Events waiting to be published (with thresholds)
- **Outbox Event Throughput** - Rate of published events
- **Optimistic Send Success Rate** - Success rate of optimistic publishing
- **Optimistic Send Latency (p95)** - Latency of immediate publish path

#### Consumer Inbox
- **Consumer Inbox Processing** - Events processed vs duplicates detected
- **Consumer Processing Duration** - Processing time percentiles

## Installation

### Option 1: Import via Grafana UI

1. Open Grafana and navigate to **Dashboards > Import**
2. Click **Upload JSON file** and select `sagaz-dashboard.json`
3. Select your Prometheus data source
4. Click **Import**

### Option 2: ConfigMap for Kubernetes

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  sagaz-dashboard.json: |
    <paste-dashboard-json-here>
```

If using the Grafana Helm chart, add:

```yaml
dashboardProviders:
  dashboardproviders.yaml:
    apiVersion: 1
    providers:
      - name: 'sagaz'
        orgId: 1
        folder: 'Sagaz'
        type: file
        options:
          path: /var/lib/grafana/dashboards/sagaz

dashboardsConfigMaps:
  sagaz: "grafana-dashboards"
```

## Required Metrics

These dashboards expect the following Prometheus metrics to be exposed:

### Saga Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `saga_execution_total{status}` | Counter | Total saga executions by status |
| `saga_step_duration_seconds` | Histogram | Step execution duration |
| `saga_compensations_total` | Counter | Total compensations triggered |

### Outbox Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `outbox_pending_events_total` | Gauge | Events pending in outbox |
| `outbox_published_events_total` | Counter | Events successfully published |
| `outbox_optimistic_send_attempts_total` | Counter | Optimistic send attempts |
| `outbox_optimistic_send_success_total` | Counter | Successful optimistic sends |
| `outbox_optimistic_send_failures_total{reason}` | Counter | Failed optimistic sends |
| `outbox_optimistic_send_latency_seconds` | Histogram | Optimistic send latency |

### Consumer Inbox Metrics
| Metric | Type | Description |
|--------|------|-------------|
| `consumer_inbox_processed_total{consumer_name,event_type}` | Counter | Processed events |
| `consumer_inbox_duplicates_total{consumer_name,event_type}` | Counter | Duplicate events skipped |
| `consumer_inbox_processing_duration_seconds` | Histogram | Processing duration |

## Exposing Metrics

Sagaz exposes metrics via the `MetricsSagaListener` and outbox components. To enable Prometheus scraping:

```python
from sagaz import SagaConfig, configure
from prometheus_client import start_http_server

# Start metrics endpoint
start_http_server(8000)  # Expose on :8000/metrics

# Configure sagaz with metrics enabled
config = SagaConfig(metrics=True)
configure(config)
```

For Kubernetes, add a ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: sagaz-metrics
spec:
  selector:
    matchLabels:
      app: your-app
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
```

## Alert Rules

See `k8s/prometheus-monitoring.yaml` for pre-configured alert rules:

- `OutboxHighLag` - >5000 pending events for 10 minutes
- `OutboxWorkerDown` - No workers running for 5 minutes
- `OutboxHighErrorRate` - >1% publish failures
- `OutboxDeadLetterQueue` - >10 DLQ events
- `OptimisticSendHighFailureRate` - >10% optimistic send failures

## Customization

### Adding Custom Panels

1. Open the dashboard in Grafana
2. Click **Add panel**
3. Configure your PromQL query
4. Save the dashboard JSON

### Modifying Thresholds

Edit the `thresholds` section in the JSON for each panel:

```json
"thresholds": {
  "mode": "absolute",
  "steps": [
    { "color": "green", "value": null },
    { "color": "yellow", "value": 1000 },
    { "color": "red", "value": 5000 }
  ]
}
```

## Support

- [Documentation](../docs/README.md)
- [GitHub Issues](https://github.com/brunolnetto/sagaz/issues)
